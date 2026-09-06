from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from . import admin_api, agent_api, api_client, hy2_api, public_api, services, subscription_api
from .config import settings
from .db import SessionLocal, init_db

log = logging.getLogger("panel")

_ROOT = Path(__file__).resolve().parent.parent.parent

PANEL_DIST = _ROOT / "panel" / "dist"


def _site_dir() -> Path | None:
    configured = settings().site_dir.strip()
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = (_ROOT / "backend" / configured).resolve()
    return path if path.is_dir() else None


async def _traffic_loop(seconds: int) -> None:
    while True:
        await asyncio.sleep(seconds)
        try:
            await asyncio.to_thread(_sync_once)
        except Exception:
            log.exception("обход серверов за трафиком не удался")


def _sync_once() -> None:
    from .services.traffic import enforce_access, reconcile_peers

    with SessionLocal() as db:
        rounds = services.sync_all_traffic(db)

        # Адреса, с которых сидят учётки VLESS, собирает тот же обход —
        # склеиваем их по узлам: один человек может сидеть сразу на двух.
        ips_by_user: dict[int, set[str]] = {}
        for item in rounds or []:
            for user_id, ips in (item.get("ips") or {}).items():
                ips_by_user.setdefault(int(user_id), set()).update(ips)
        # Узлы с агентом обход пропустил — их адреса берём из снимков.
        for user_id, ips in services.agent.recent_ips().items():
            ips_by_user.setdefault(user_id, set()).update(ips)

        closed = enforce_access(db)
        if closed:
            log.info("доступ закрыт по лимиту или сроку: %s", closed)

        for server in services.active_servers(db):
            # Выдачи awg из свежего снимка агента — без SSH; иначе обход сам сходит.
            for public_key in reconcile_peers(db, server, dumps=services.agent.awg_dumps(server)):
                log.warning(
                    "сняли лишний пир с «%s»: %s… — в базе живого ключа нет",
                    server.name,
                    public_key[:16],
                )

        # Отметки живости только что обновил обход выше — сразу и смотрим,
        # не пора ли сказать админам. Отдельный цикл ходил бы к базе за тем
        # же самым.
        try:
            sent = services.alerts.check_nodes(db)
            if sent:
                log.info("оповещения о узлах: %s", ", ".join(sent))
        except Exception:
            log.exception("оповещение о состоянии узлов не удалось")

        # Живость по протоколам — из снимков агентов, где они стоят.
        try:
            troubled = services.agent.check_agents(db)
            if troubled:
                log.info("оповещения о службах узлов: %s", ", ".join(troubled))
        except Exception:
            log.exception("проверка снимков агентов не удалась")

        try:
            shared = services.alerts.check_sharing(db, ips_by_user)
            if shared:
                log.info("ключ на нескольких устройствах: %s", ", ".join(shared))
        except Exception:
            log.exception("проверка общего ключа не удалась")


async def _delivery_loop(seconds: int) -> None:
    tick = 0
    while True:
        await asyncio.sleep(seconds)
        tick += 1
        try:
            await asyncio.to_thread(_delivery_once, tick)
        except Exception:
            log.exception("обход очереди доставки не удался")


def _delivery_once(tick: int) -> None:
    with SessionLocal() as db:
        services.delivery.run_once(db)
        services.billing_webhook.retry_stuck(db)
        services.recurring.retry_stuck(db)
        services.delivery.queue_expiry_reminders(db)

        # Паузы, которые стоят дольше положенного, снимаем сами: человек,
        # забывший про заморозку, иначе сидит без доступа бессрочно.
        woken = services.freeze.auto_resume(db)
        if woken:
            log.info("пауза снята по сроку: %s", ", ".join(woken))

        if tick % 100 == 1:
            services.expire_stale(db)
            services.ratelimit.sweep(db)
            services.telemetry.prune(db)


async def _telemetry_loop() -> None:
    """Раз в час: база провайдеров, тревога о просадках, суточная сводка."""
    while True:
        try:
            await asyncio.to_thread(_telemetry_once)
        except Exception:
            log.exception("часовой цикл телеметрии не удался")
        await asyncio.sleep(3600)


def _telemetry_once() -> None:
    services.asn.refresh_if_stale()
    with SessionLocal() as db:
        dropped = services.telemetry.check_drops(db)
        if dropped:
            log.warning("похоже на блокировку: %s", ", ".join(dropped))
        if services.telemetry.daily_digest(db):
            log.warning("сводка по связи отправлена админам")


async def _ton_loop(seconds: int) -> None:
    while True:
        await asyncio.sleep(seconds)
        try:
            await asyncio.to_thread(_ton_once)
        except Exception:
            log.exception("сверка TON-платежей не удалась")


def _ton_once() -> None:
    with SessionLocal() as db:
        services.ton_watcher.run_once(db)


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
        tasks.append(asyncio.create_task(_telemetry_loop()))
    if config.ton_wallet_address.strip() and config.ton_poll_seconds > 0:
        tasks.append(asyncio.create_task(_ton_loop(config.ton_poll_seconds)))

    yield

    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


_docs = settings().debug
app = FastAPI(
    title="Prosto VPN — панель",
    description=(
        "Пользователи, серверы, подписки и деньги. "
        "/api/v1 — приложениям и сайту, /api/admin — панели."
    ),
    version="2.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_INLINE_SCRIPT = re.compile(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", re.S)
_csp_cache: dict[str, tuple[float, str]] = {}


def _inline_hashes(index: Path) -> str:
    try:
        stamp = index.stat().st_mtime
    except OSError:
        return ""
    cached = _csp_cache.get(str(index))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        html = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    parts = [
        "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
        for body in _INLINE_SCRIPT.findall(html)
    ]
    value = " ".join(parts)
    _csp_cache[str(index)] = (stamp, value)
    return value


def _csp_for(path: str) -> str:
    site = _site_dir()
    index = None
    admin = path.startswith("/admin")
    if site is not None:
        candidate = site.parent.parent / "panel" / "dist" / "index.html"
        index = candidate if admin and candidate.is_file() else site / "index.html"
    hashes = _inline_hashes(index) if index is not None else ""
    # Сайт открывается и как мини-приложение Telegram: на телефонах это
    # WebView, а в Telegram Web — iframe с web.telegram.org, поэтому сайту
    # (но не админке) нужны их скрипт и право показываться в этом iframe.
    script_src = "script-src 'self' " + ("" if admin else "https://telegram.org ") + hashes
    # Аватар пользователя в мини-аппе приходит с t.me (initDataUnsafe.user.photo_url),
    # а логотипы кошельков в модалке TON Connect — с CDN самих кошельков,
    # список которых живёт своей жизнью. Сайту разрешаем любые https-картинки.
    img_src = "img-src 'self' data: blob:" + ("" if admin else " https:")
    ancestors = "frame-ancestors 'none'" if admin else (
        "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
    )
    return "; ".join(
        [
            "default-src 'self'",
            script_src.strip(),
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com data:",
            img_src,
            # TON Connect ходит на мосты кошельков (SSE) и за списком
            # кошельков — адреса меняются вместе со списком, поэтому сайту
            # открываем https/wss. Админка остаётся на 'self'.
            "connect-src 'self'" if admin else "connect-src 'self' https: wss:",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            ancestors,
            "upgrade-insecure-requests",
        ]
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # X-Frame-Options не умеет списки разрешённых, а сайту нужно открываться
    # в iframe Telegram Web — для него хватает frame-ancestors из CSP
    # (браузеры с поддержкой CSP2 ставят его выше XFO). Админке — запрет.
    if request.url.path.startswith("/admin"):
        response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=(), payment=(), usb=(), interest-cohort=()",
    )
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    # Ответы кабинета и админки — с паролями, ссылками и ключами: ни браузеру,
    # ни прокси их хранить нельзя.
    if request.url.path.startswith(("/api/v1/account", "/api/admin")):
        response.headers.setdefault("Cache-Control", "no-store")
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        response.headers.setdefault("Content-Security-Policy", _csp_for(request.url.path))
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
    return response


@app.exception_handler(StarletteHTTPException)
async def _json_errors(request: Request, exc: StarletteHTTPException):
    path = request.url.path
    if not (path.startswith("/api/") or path.startswith("/s/")):
        site = _site_dir()
        if site is not None and exc.status_code == 404 and (site / "404.html").is_file():
            return FileResponse(site / "404.html", status_code=404)
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
app.include_router(subscription_api.router)
app.include_router(hy2_api.router)
app.include_router(agent_api.router)


if PANEL_DIST.is_dir():
    app.mount("/admin/assets", StaticFiles(directory=PANEL_DIST / "assets"), name="panel-assets")

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{full_path:path}", include_in_schema=False)
    def panel_spa(full_path: str = "") -> FileResponse:
        root = PANEL_DIST.resolve()
        candidate = (root / full_path).resolve()
        if full_path and not _hidden_path(full_path) and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


def _hidden_path(full_path: str) -> bool:
    """Скрытые файлы (.env, .git, .map-исходники с точкой) наружу не отдаём."""
    return any(part.startswith(".") for part in full_path.split("/") if part)


_SITE = _site_dir()

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

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def site_spa(full_path: str = "") -> FileResponse | RedirectResponse:
        target = _LEGACY_PAGES.get(full_path)
        if target is not None:
            return RedirectResponse(target, status_code=301)

        root = _SITE.resolve()
        candidate = (root / full_path).resolve()
        if full_path and not _hidden_path(full_path) and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")

    log.info("сайт раздаётся из %s (одностраничный)", _SITE)
elif _SITE is not None:
    app.mount("/", StaticFiles(directory=_SITE, html=True), name="site")
    log.info("сайт раздаётся из %s", _SITE)
elif PANEL_DIST.is_dir():
    log.info("сайт не найден, в корне только панель")


def main() -> None:
    import uvicorn

    config = settings()
    # Только петля: наружу панель смотрит через nginx, а X-Forwarded-For с
    # чужих адресов нельзя ни считать, ни доверять.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=config.debug)


if __name__ == "__main__":
    main()
