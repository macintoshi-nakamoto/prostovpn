"""
API для приложений: вход по логину и паролю, список серверов с конфигами.

Список серверов отдаётся целиком при каждом запросе, поэтому добавленный
в панели сервер появляется у всех при следующем открытии приложения —
раздавать его вручную не нужно.

Наружу не уходит ничего, что приложению нечего показывать: ни адреса
сервера, ни публичного ключа, ни выданного адреса в подсети. Остаётся
страна с городом — то, из чего человек выбирает, — и сам конфиг, который
приложение отдаёт туннелю, но не рисует на экране.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from . import services
from .db import get_db
from .models import Provisioning, Session, User
from .provisioning import config_for

router = APIRouter(prefix="/api/v1", tags=["client"])


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)


class ServerOut(BaseModel):
    """
    Точка подключения глазами приложения.

    `config` — единственное техническое поле: его отдают туннелю как есть.
    Показывать его пользователю нельзя, и показывать нечего — всё, что
    нужно на экране, лежит в стране и городе.
    """

    id: int
    name: str
    country: str | None = None
    country_en: str | None = None
    city: str | None = None
    city_en: str | None = None
    country_code: str | None = None
    config: str


class SubscriptionOut(BaseModel):
    active: bool
    plan: str | None = None
    expires_at: dt.datetime | None = None
    days_left: int | None = None
    # Трафик в байтах: лимит None — безлимит.
    traffic_used_bytes: int = 0
    traffic_limit_bytes: int | None = None


class AccountOut(BaseModel):
    public_id: str
    login: str
    name: str | None = None


class LoginResponse(BaseModel):
    token: str
    expires_at: dt.datetime
    account: AccountOut
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
    limit = user.effective_traffic_limit()
    if sub is None:
        return SubscriptionOut(
            active=False,
            traffic_used_bytes=user.traffic_used_bytes,
            traffic_limit_bytes=limit,
        )
    left = sub.expires_at - services.utcnow()
    return SubscriptionOut(
        active=True,
        plan=sub.plan,
        expires_at=sub.expires_at,
        days_left=max(0, left.days),
        traffic_used_bytes=user.traffic_used_bytes,
        traffic_limit_bytes=limit,
    )


def _provision_missing_keys(user_id: int) -> None:
    """
    Досоздаёт недостающие ключи в фоне, уже после ответа приложению.

    Раньше это делалось прямо в запросе, и вход занимал столько, сколько
    тупит самый медленный сервер: недоступный узел добавляет секунды
    ожидания на каждого. Ключи обычно уже есть — их выдают при создании
    пользователя, — а те, что появились из-за нового сервера, подтянутся
    к следующему запросу списка.
    """
    from .db import SessionLocal

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is not None and user.has_access():
            services.ensure_keys(db, user)


def _servers_out(db: OrmSession, user: User, background: BackgroundTasks | None = None) -> list[ServerOut]:
    """
    Серверы, доступные пользователю прямо сейчас.

    Без действующей подписки список пустой: платящий и неплатящий не должны
    получать одно и то же.
    """
    if not user.has_access():
        return []

    by_server = {key.server_id: key for key in user.keys if key.revoked_at is None}

    # Чего-то не хватает — досоздадим после ответа, не задерживая человека.
    if background is not None:
        missing = any(
            server.id not in by_server and server.provisioning != Provisioning.SHARED
            for server in services.active_servers(db)
        )
        if missing:
            background.add_task(_provision_missing_keys, user.id)

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
                # Имя для списка — страна, а не внутреннее название сервера:
                # «Нидерланды» человеку понятнее, чем «nl-ams-01».
                name=server.country or server.name,
                country=server.country,
                country_en=server.country_en,
                city=server.city,
                city_en=server.city_en,
                country_code=server.country_code,
                config=config,
            )
        )
    return out


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    background: BackgroundTasks,
    db: OrmSession = Depends(get_db),
) -> LoginResponse:
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
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=_servers_out(db, user, background),
    )


@router.get("/servers", response_model=ServersResponse)
def servers(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> ServersResponse:
    services.touch(db, session, _client_ip(request))
    user = session.user
    return ServersResponse(
        subscription=_subscription_out(user), servers=_servers_out(db, user, background)
    )


@router.post("/heartbeat")
def heartbeat(
    request: Request,
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    """Приложение отмечается, пока подключено — из этого видно живые сессии."""
    services.touch(db, session, _client_ip(request))
    user = session.user
    return {"ok": True, "active": user.has_access(), "subscription": _subscription_out(user).model_dump()}


class UpdateOut(BaseModel):
    """Что приложение показывает на кнопке обновления."""

    update_available: bool
    version: str | None = None
    url: str | None = None
    changelog: str | None = None
    released_at: dt.datetime | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    # Обязательное обновление: без него сервис не работает.
    mandatory: bool = False


@router.get("/version", response_model=UpdateOut)
def version(
    platform: str,
    current: str | None = None,
    db: OrmSession = Depends(get_db),
) -> UpdateOut:
    """
    Есть ли версия новее установленной.

    Без токена: приложение спрашивает это и на экране входа, когда сессии
    ещё нет, а обязательное обновление должно дойти и до тех, кто не вошёл.
    """
    return UpdateOut(**services.check_update(db, platform, current))


@router.post("/logout")
def logout(
    session: Session = Depends(current_session), db: OrmSession = Depends(get_db)
) -> dict[str, bool]:
    session.revoked_at = services.utcnow()
    db.commit()
    return {"ok": True}
