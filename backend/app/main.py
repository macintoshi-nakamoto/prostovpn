"""Точка входа панели: uvicorn app.main:app"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from . import admin_api, api_client, public_api, services, subscription_api
from .config import settings
from .db import SessionLocal, init_db

log = logging.getLogger("panel")

_ROOT = Path(__file__).resolve().parent.parent.parent

# Собранная веб-панель. Если её нет — работает только API, и это нормально:
# в разработке панель поднимает Vite на своём порту.
PANEL_DIST = _ROOT / "panel" / "dist"


def _site_dir() -> Path | None:
    """
    Каталог публичного сайта.

    Раздавать его самим удобно на одном сервере и одной команде запуска. На
    боевом сервере статику обычно отдаёт nginx — тогда `PANEL_SITE_DIR`
    очищают, и приложение просто не берёт эти маршруты.
    """
    configured = settings().site_dir.strip()
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = (_ROOT / "backend" / configured).resolve()
    return path if path.is_dir() else None


async def _traffic_loop(seconds: int) -> None:
    """
    Периодический обход узлов.

    Одним заходом снимаются три вещи сразу: расход трафика, время
    последнего рукопожатия — по нему видно, подключён ли человек, — и
    срабатывание лимита. Поэтому интервал здесь секундный, а не минутный:
    статус «онлайн», обновляемый раз в четверть часа, показывал бы
    подключённым того, кто давно вышел.

    Первый заход отложен: на старте приложение и так занято.
    """
    while True:
        await asyncio.sleep(seconds)
        try:
            # SSH — блокирующий, поэтому уводим в отдельный поток, иначе
            # недоступный сервер повесит весь событийный цикл.
            await asyncio.to_thread(_sync_once)
        except Exception:  # pragma: no cover - фоновая задача не должна падать
            log.exception("обход серверов за трафиком не удался")


def _sync_once() -> None:
    from .services.traffic import enforce_access, reconcile_peers

    with SessionLocal() as db:
        services.sync_all_traffic(db)

        closed = enforce_access(db)
        if closed:
            log.info("доступ закрыт по лимиту или сроку: %s", closed)

        # Сверка в обратную сторону: пир на узле, которому в базе ничего не
        # соответствует, — это работающий доступ, которого никто не видит.
        for server in services.active_servers(db):
            for public_key in reconcile_peers(db, server):
                log.warning(
                    "сняли лишний пир с «%s»: %s… — в базе живого ключа нет",
                    server.name,
                    public_key[:16],
                )


async def _delivery_loop(seconds: int) -> None:
    """
    Очередь доставки и уборка вокруг неё.

    Один цикл на три дела, потому что все три дёшевы и все три обязаны
    случаться регулярно: разослать то, что не ушло сразу; добить выдачу по
    заказам, обработка которых сорвалась; закрыть неоплаченные заказы,
    которым больше суток.
    """
    tick = 0
    while True:
        await asyncio.sleep(seconds)
        tick += 1
        try:
            await asyncio.to_thread(_delivery_once, tick)
        except Exception:  # pragma: no cover - фоновая задача не должна падать
            log.exception("обход очереди доставки не удался")


def _delivery_once(tick: int) -> None:
    with SessionLocal() as db:
        services.delivery.run_once(db)
        services.billing_webhook.retry_stuck(db)
        # События подписок живут по своим правилам — у них свой обходчик:
        # провайдер повтор не пришлёт, упавшее списание лечится только так.
        services.recurring.retry_stuck(db)
        # Напоминания о скором конце подписки. Дёшево: выборка по
        # индексированному expires_at, и почти всегда пустая.
        services.delivery.queue_expiry_reminders(db)
        # Просроченные заказы и счётчики частоты — раз в сотню циклов:
        # каждые пятнадцать секунд их перебирать незачем.
        if tick % 100 == 1:
            services.expire_stale(db)
            services.ratelimit.sweep(db)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()

    config = settings()
    if config.seed_demo:
        from .seed import seed_demo

        with SessionLocal() as db:
            seed_demo(db)

    for problem in config.is_production_ready:
        log.warning("конфигурация: %s", problem)

    # Интервал в минутах проигрывает секундам (см. traffic_interval_seconds),
    # поэтому администратор, поправивший только его, не увидит эффекта и
    # решит, что панель его не слушается. Говорим об этом прямо.
    if config.traffic_sync_minutes > 0 and config.traffic_sync_seconds > 0:
        log.warning(
            "конфигурация: PANEL_TRAFFIC_SYNC_MINUTES=%s не действует, "
            "интервал обхода задаёт PANEL_TRAFFIC_SYNC_SECONDS=%s",
            config.traffic_sync_minutes,
            config.traffic_sync_seconds,
        )

    tasks: list[asyncio.Task] = []
    if config.traffic_interval_seconds > 0:
        tasks.append(asyncio.create_task(_traffic_loop(config.traffic_interval_seconds)))
    if config.delivery_poll_seconds > 0:
        tasks.append(asyncio.create_task(_delivery_loop(config.delivery_poll_seconds)))

    yield

    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Prosto VPN — панель",
    description=(
        "Пользователи, серверы, подписки и деньги. "
        "/api/v1 — приложениям и сайту, /api/admin — панели."
    ),
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """
    Заголовки безопасности на всё, что отдаёт приложение.

    HSTS ставится только на HTTPS-запросах: выданный по обычному http, он
    в лучшем случае игнорируется, а в худшем запирает разработчика на
    localhost без возможности открыть страницу.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
    return response


@app.exception_handler(StarletteHTTPException)
async def _json_errors(request: Request, exc: StarletteHTTPException):
    """
    Ошибки API — JSON, ошибки страниц сайта — страница.

    Сайт отдаётся тем же приложением, и 404 на опечатку в адресе не должна
    показывать человеку `{"detail":"Not Found"}`. Подписка /s/ — наоборот:
    её дёргает клиент, ему нужен JSON, а не страница 404 сайта.
    """
    path = request.url.path
    if not (path.startswith("/api/") or path.startswith("/s/")):
        site = _site_dir()
        if site is not None and exc.status_code == 404 and (site / "404.html").is_file():
            return FileResponse(site / "404.html", status_code=404)
    # Заголовки ответа переносим как есть. Ответ здесь собирается заново, и
    # без этой строки терялось всё, что маршрут к ошибке приложил: Retry-After
    # у ограничителя частоты и X-Error-Code, по которому приложение выбирает
    # свой перевод вместо русского текста панели.
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_client.router)
app.include_router(public_api.router)
app.include_router(admin_api.router)
# Подписка живёт в корне поддомена (/s/...), без префикса /api. Подключаем до
# site-catch-all ниже, иначе тот проглотил бы /s/ как маршрут SPA.
app.include_router(subscription_api.router)


# --- статика ------------------------------------------------------------------
#
# Порядок важен: сначала админка на своём префиксе, потом сайт в корне.
# Панель живёт на /admin, чтобы корень остался за сайтом и чтобы перед ней
# можно было поставить отдельный фильтр по адресам или basic-auth, не
# задевая публичные страницы.

if PANEL_DIST.is_dir():
    app.mount("/admin/assets", StaticFiles(directory=PANEL_DIST / "assets"), name="panel-assets")

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{full_path:path}", include_in_schema=False)
    def panel_spa(full_path: str = "") -> FileResponse:
        """
        Всё, что не API, отдаём индексом панели.

        Маршрутизация у SPA своя: по прямой ссылке на /admin/users сервер
        обязан вернуть тот же index.html, иначе перезагрузка даёт 404.
        """
        # resolve() и проверка каталога обязательны: uvicorn не схлопывает
        # «..» в пути, и без них запрос вида /admin/../../backend/.env отдал
        # бы файл с секретами. Нормализация в nginx тут не защита — до 8000
        # можно достучаться и напрямую.
        root = PANEL_DIST.resolve()
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


_SITE = _site_dir()

# Адреса страниц старого сайта. Они разошлись по установленным приложениям
# и по чужим ссылкам, поэтому после переезда на SPA продолжают работать —
# уводят на новый маршрут, а не в 404.
_LEGACY_PAGES = {
    "faq.html": "/faq",
    "privacy.html": "/privacy",
    "offer.html": "/terms",
    "contacts.html": "/contacts",
    "account.html": "/account",
    "download.html": "/#app",
    "index.html": "/",
}

if _SITE is not None and settings().site_spa:

    # response_model=None: из объединённой аннотации FastAPI пытается собрать
    # модель ответа и падает — здесь возвращается готовый Response.
    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def site_spa(full_path: str = "") -> FileResponse | RedirectResponse:
        """
        Сайт-одностраничник: файл, если он есть, иначе index.html.

        Маршрутизация у SPA своя, и по прямой ссылке на /account сервер
        обязан вернуть тот же index.html — иначе перезагрузка страницы даёт
        404. Маршруты /api и /admin сюда не попадают: они объявлены выше, а
        FastAPI выбирает первый подошедший.
        """
        target = _LEGACY_PAGES.get(full_path)
        if target is not None:
            return RedirectResponse(target, status_code=301)

        # resolve() и проверка каталога обязательны: uvicorn не схлопывает
        # «..» в пути, и без них запрос вида /../backend/.env отдал бы файл
        # с секретами.
        root = _SITE.resolve()
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")

    log.info("сайт раздаётся из %s (одностраничный)", _SITE)
elif _SITE is not None:
    app.mount("/", StaticFiles(directory=_SITE, html=True), name="site")
    log.info("сайт раздаётся из %s", _SITE)
elif PANEL_DIST.is_dir():
    log.info("сайт не найден, в корне только панель")


def main() -> None:  # pragma: no cover - запуск руками
    import uvicorn

    config = settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=config.debug)


if __name__ == "__main__":  # pragma: no cover
    main()
