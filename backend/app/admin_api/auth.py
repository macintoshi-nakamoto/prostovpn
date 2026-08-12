"""Вход в веб-панель."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin
from ..security import client_ip
from . import schemas
from .deps import current_admin

router = APIRouter(tags=["admin:auth"])


@router.post("/login", response_model=schemas.LoginResponse)
def login(
    body: schemas.LoginRequest, request: Request, db: OrmSession = Depends(get_db)
) -> schemas.LoginResponse:
    try:
        admin, token, expires_at = services.authenticate_admin(
            db, body.login, body.password, ip=client_ip(request)
        )
    except services.LoginThrottled as exc:
        # 429 отдельно от 401 и до него: LoginThrottled — наследник
        # PanelError, и без своей ветки троттлинг пришёл бы в панель как
        # «неверный логин или пароль», без Retry-After и без объяснения.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return schemas.LoginResponse(token=token, expires_at=expires_at, login=admin.login)


@router.post("/logout", response_model=schemas.ActionResult)
def logout(
    authorization: str | None = Header(default=None),
    db: OrmSession = Depends(get_db),
) -> schemas.ActionResult:
    if authorization and authorization.lower().startswith("bearer "):
        session = services.admin_session_for_token(db, authorization.split(" ", 1)[1].strip())
        if session is not None:
            services.revoke_admin_session(db, session)
    # Выход всегда успешен: токена уже нет — цель достигнута.
    return schemas.ActionResult(ok=True)


@router.get("/me")
def me(admin: Admin = Depends(current_admin)) -> dict[str, object]:
    return {"id": admin.id, "login": admin.login}
