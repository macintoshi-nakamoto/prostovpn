from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin
from ..security import client_ip
from . import schemas
from .deps import audit, current_admin

router = APIRouter(tags=["admin:auth"])


@router.post("/login", response_model=schemas.LoginResponse)
def login(
    body: schemas.LoginRequest, request: Request, db: OrmSession = Depends(get_db)
) -> schemas.LoginResponse:
    try:
        admin, token, expires_at = services.authenticate_admin(
            db, body.login, body.password, ip=client_ip(request), code=body.code
        )
    except services.LoginThrottled as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except services.PanelError as exc:
        headers = {"X-Error-Code": exc.code} if exc.code else None
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc), headers=headers) from exc
    return schemas.LoginResponse(token=token, expires_at=expires_at, login=admin.login)


@router.get("/totp", response_model=schemas.TotpStatus)
def totp_status(admin: Admin = Depends(current_admin)) -> schemas.TotpStatus:
    return schemas.TotpStatus(
        enabled=admin.totp_enabled,
        enabled_at=admin.totp_enabled_at,
        pending=bool(admin.totp_pending_enc),
    )


@router.post("/totp/setup", response_model=schemas.TotpSetupOut)
def totp_setup(
    db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.TotpSetupOut:
    """Секрет для приложения-аутентификатора. Включится после подтверждения кодом."""
    try:
        secret, uri = services.totp_begin(db, admin)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return schemas.TotpSetupOut(secret=secret, otpauth_url=uri)


@router.post("/totp/enable", response_model=schemas.TotpStatus)
def totp_enable(
    body: schemas.TotpCodeIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.TotpStatus:
    try:
        services.totp_enable(db, admin, body.code)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "admin.totp_on", admin.login)
    db.commit()
    return totp_status(admin)


@router.post("/totp/disable", response_model=schemas.TotpStatus)
def totp_disable(
    body: schemas.TotpCodeIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.TotpStatus:
    try:
        services.totp_disable(db, admin, body.code)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "admin.totp_off", admin.login)
    db.commit()
    return totp_status(admin)


@router.post("/logout", response_model=schemas.ActionResult)
def logout(
    authorization: str | None = Header(default=None),
    db: OrmSession = Depends(get_db),
) -> schemas.ActionResult:
    if authorization and authorization.lower().startswith("bearer "):
        session = services.admin_session_for_token(db, authorization.split(" ", 1)[1].strip())
        if session is not None:
            services.revoke_admin_session(db, session)
    return schemas.ActionResult(ok=True)


@router.get("/me")
def me(admin: Admin = Depends(current_admin)) -> dict[str, object]:
    return {"id": admin.id, "login": admin.login, "totpEnabled": admin.totp_enabled}
