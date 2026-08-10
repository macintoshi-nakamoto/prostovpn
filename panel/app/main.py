"""Точка входа панели: uvicorn app.main:app"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from . import admin_api, api_client, services
from .config import settings
from .db import SessionLocal, init_db

log = logging.getLogger("panel")

# Собранная веб-панель. Если её нет — работает только API, и это нормально:
# в разработке панель поднимает Vite на своём порту.
PANEL_DIST = Path(__file__).resolve().parent.parent.parent / "panel" / "dist"


async def _traffic_loop(minutes: int) -> None:
    """
    Периодический обход серверов за счётчиками трафика.

    Первый заход отложен: на старте приложение и так занято, а счётчики за
    минуту не убегут.
    """
    interval = minutes * 60
    while True:
        await asyncio.sleep(interval)
        try:
            # SSH — блокирующий, поэтому уводим в отдельный поток, иначе
            # недоступный сервер повесит весь событийный цикл.
            await asyncio.to_thread(_sync_once)
        except Exception:  # pragma: no cover - фоновая задача не должна падать
            log.exception("обход серверов за трафиком не удался")


def _sync_once() -> None:
    with SessionLocal() as db:
        services.sync_all_traffic(db)
        from .services.traffic import enforce_traffic_limits

        enforce_traffic_limits(db)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()

    config = settings()
    if config.seed_demo:
        from .seed import seed_demo

        with SessionLocal() as db:
            seed_demo(db)

    task: asyncio.Task | None = None
    if config.traffic_sync_minutes > 0:
        task = asyncio.create_task(_traffic_loop(config.traffic_sync_minutes))

    yield

    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Prosto VPN — панель",
    description="Пользователи, серверы, подписки и деньги. /api/v1 — приложениям, /api/admin — панели.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def _json_errors(_request: Request, exc: StarletteHTTPException):
    """Ошибки всегда JSON: панель и приложения читают их одинаково."""
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_client.router)
app.include_router(admin_api.router)


if PANEL_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=PANEL_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """
        Всё, что не API, отдаём индексом панели.

        Маршрутизация у SPA своя: по прямой ссылке на /users сервер обязан
        вернуть тот же index.html, иначе перезагрузка страницы даёт 404.
        """
        candidate = PANEL_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(PANEL_DIST / "index.html")


def main() -> None:  # pragma: no cover - запуск руками
    import uvicorn

    config = settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=config.debug)


if __name__ == "__main__":  # pragma: no cover
    main()
