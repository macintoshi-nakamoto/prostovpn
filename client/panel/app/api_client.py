"""
API для приложений: вход по логину и паролю, список серверов с конфигами.

Список серверов отдаётся целиком при каждом запросе, поэтому добавленный
в панели сервер появляется у всех при следующем открытии приложения —
раздавать его вручную не нужно.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from . import services
from .db import get_db
from .models import Session, User
from .provisioning import build_vpn_key, config_for

router = APIRouter(prefix="/api/v1", tags=["client"])


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)


class ServerOut(BaseModel):
    id: int
    name: str
    country: str | None = None
    country_en: str | None = None
    city: str | None = None
    city_en: str | None = None
    country_code: str | None = None
    host: str
    port: int
    # wg-quick для туннеля и та же конфигурация ссылкой — приложению удобно
    # первое, ручной вставке и клиенту Amnezia второе.
    config: str
    key: str


class SubscriptionOut(BaseModel):
    active: bool
    plan: str | None = None
    expires_at: dt.datetime | None = None
    days_left: int | None = None


class LoginResponse(BaseModel):
    token: str
    expires_at: dt.datetime
    login: str
    subscription: SubscriptionOut
    servers: list[ServerOut]


class ServersResponse(BaseModel):
    subscription: SubscriptionOut
    servers: list[ServerOut]


def _client_ip(request: Request) -> str | None:
    # За обратным прокси реальный адрес приходит заголовком
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def current_session(
    authorization: str | None = Header(default=None),
    db: OrmSession = Depends(get_db),
) -> Session:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен токен")
    session = services.session_for_token(db, authorization.split(" ", 1)[1].strip())
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен недействителен")
    return session


def _subscription_out(user: User) -> SubscriptionOut:
    sub = user.active_subscription()
    if sub is None:
        return SubscriptionOut(active=False)
    left = sub.expires_at - services.utcnow()
    return SubscriptionOut(
        active=True,
        plan=sub.plan,
        expires_at=sub.expires_at,
        days_left=max(0, left.days),
    )


def _servers_out(db: OrmSession, user: User) -> list[ServerOut]:
    """
    Серверы, доступные пользователю прямо сейчас.

    Без действующей подписки список пустой: платящий и неплатящий не должны
    получать одно и то же.
    """
    if not user.has_access():
        return []

    services.ensure_keys(db, user)
    db.refresh(user)
    by_server = {key.server_id: key for key in user.keys if key.revoked_at is None}

    out: list[ServerOut] = []
    for server in services.active_servers(db):
        config = config_for(server, by_server.get(server.id))
        if not config:
            # Сервер есть, но конфига для этого человека пока нет —
            # показывать его в приложении нельзя: подключение упадёт.
            continue
        out.append(
            ServerOut(
                id=server.id,
                name=server.name,
                country=server.country,
                country_en=server.country_en,
                city=server.city,
                city_en=server.city_en,
                country_code=server.country_code,
                host=server.host,
                port=server.port,
                config=config,
                key=build_vpn_key(server.host, config, server.port),
            )
        )
    return out


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: OrmSession = Depends(get_db)) -> LoginResponse:
    try:
        user, token = services.authenticate(
            db,
            login=body.login,
            password=body.password,
            platform=body.platform,
            app_version=body.app_version,
            ip=_client_ip(request),
        )
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    session = services.session_for_token(db, token)
    assert session is not None
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        login=user.login,
        subscription=_subscription_out(user),
        servers=_servers_out(db, user),
    )


@router.get("/servers", response_model=ServersResponse)
def servers(
    request: Request,
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> ServersResponse:
    services.touch(db, session, _client_ip(request))
    user = session.user
    return ServersResponse(subscription=_subscription_out(user), servers=_servers_out(db, user))


@router.post("/heartbeat")
def heartbeat(
    request: Request,
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    """Приложение отмечается, пока подключено — из этого видно живые сессии."""
    services.touch(db, session, _client_ip(request))
    return {"ok": True, "active": session.user.has_access()}


@router.post("/logout")
def logout(
    session: Session = Depends(current_session), db: OrmSession = Depends(get_db)
) -> dict[str, bool]:
    session.revoked_at = services.utcnow()
    db.commit()
    return {"ok": True}
