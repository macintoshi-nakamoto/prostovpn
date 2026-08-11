"""Точка входа панели: uvicorn app.main:app"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from . import admin, api_client
from .config import settings
from .db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Prosto VPN — панель",
    description="Пользователи, серверы, подписки и деньги. /api/v1 — для приложений.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(StarletteHTTPException)
async def _redirect_to_login(request: Request, exc: StarletteHTTPException):
    """
    Незалогиненного администратора уводим на форму входа, а не показываем
    голую ошибку. Для API оставляем обычный JSON: приложению нужен код.
    """
    location = (exc.headers or {}).get("Location")
    if exc.status_code == 303 and location:
        return RedirectResponse(location, status_code=303)
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_client.router)
app.include_router(admin.router)


def main() -> None:  # pragma: no cover - запуск руками
    import uvicorn

    config = settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=config.debug)


if __name__ == "__main__":  # pragma: no cover
    main()
