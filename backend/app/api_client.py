from __future__ import annotations

import datetime as dt
import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from . import geo, provisioning, services
from .config import settings
from .db import get_db
from .models import (
    NodeEndpoint,
    Provisioning,
    Server,
    Session,
    User,
    UserKey,
    is_ios_slot,
    utcnow,
)
from .provisioning import serving_config
from .security import client_ip, ip_tag

log = logging.getLogger("panel.client")

router = APIRouter(prefix="/api/v1", tags=["client"])


def _error_code_header(exc: services.PanelError) -> dict[str, str] | None:
    code = getattr(exc, "code", "")
    return {"X-Error-Code": code} if code else None


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=96)


class ServerOut(BaseModel):

    id: int
    name: str
    country: str | None = None
    country_en: str | None = None
    city: str | None = None
    city_en: str | None = None
    country_code: str | None = None
    config: str
    alt_ports: list[int] = []


class SubscriptionOut(BaseModel):
    active: bool
    plan: str | None = None
    expires_at: dt.datetime | None = None
    days_left: int | None = None
    traffic_used_bytes: int = 0
    traffic_limit_bytes: int | None = None

    traffic_left_bytes: int | None = None
    traffic_low: bool = False

    expires_soon: bool = False
    renew_url: str | None = None


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
    subscription_url: str | None = None
    notice: str | None = None


class ServersResponse(BaseModel):
    subscription: SubscriptionOut
    servers: list[ServerOut]
    notice: str | None = None


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


TRAFFIC_LOW_CAP_BYTES = 5 * 1024**3

EXPIRES_SOON_DAYS = 3


def _traffic_low_threshold(limit: int) -> int:
    return min(TRAFFIC_LOW_CAP_BYTES, limit // 5)


def _subscription_out(user: User) -> SubscriptionOut:
    sub = user.active_subscription()
    limit = user.effective_traffic_limit()
    used = user.traffic_used_bytes

    left_bytes = max(0, limit - used) if limit is not None else None
    traffic_low = left_bytes is not None and left_bytes <= _traffic_low_threshold(limit)
    exhausted = left_bytes == 0

    if sub is None:
        return SubscriptionOut(
            active=False,
            traffic_used_bytes=used,
            traffic_limit_bytes=limit,
            traffic_left_bytes=left_bytes,
            traffic_low=traffic_low,
            expires_soon=True,
            renew_url=_renew_url(),
        )

    days_left = max(0, (sub.expires_at - services.utcnow()).days)
    expires_soon = days_left <= EXPIRES_SOON_DAYS

    return SubscriptionOut(
        active=True,
        plan=sub.plan,
        expires_at=sub.expires_at,
        days_left=days_left,
        traffic_used_bytes=used,
        traffic_limit_bytes=limit,
        traffic_left_bytes=left_bytes,
        traffic_low=traffic_low,
        expires_soon=expires_soon,
        renew_url=_renew_url() if expires_soon or traffic_low or exhausted else None,
    )


def _renew_url() -> str:
    return f"{settings().site_url.rstrip('/')}/account"


def _subscription_url(db: OrmSession, session: Session) -> str | None:
    if not session.is_device:
        return None
    return services.subscription.url_for(services.subscription.mint_for_session(db, session))


def _provision_missing_keys(user_id: int, device_id: str) -> None:
    from .db import SessionLocal

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.has_access():
            return
        if device_id not in user.devices():
            log.info("фоновая выдача пропущена: устройство %s уже отвязано", device_id or "(учётки)")
            return
        services.ensure_keys(db, user, devices={device_id})


def _notice_for(db: OrmSession, user: User, servers: list[ServerOut]) -> str | None:
    if servers:
        return None

    if user.is_blocked:
        return "Доступ заблокирован. Напишите в поддержку."
    if not user.is_active:
        return "Доступ приостановлен. Напишите в поддержку."

    if user.active_subscription() is None:
        return "Подписка закончилась. Продлите её в личном кабинете на сайте."
    if user.traffic_exhausted():
        return "Закончился трафик по тарифу. Он обновится при продлении подписки."

    active = services.active_servers(db)
    if not active:
        return "Серверы временно недоступны. Мы уже занимаемся этим — попробуйте позже."

    if not any(services.can_serve(server) for server in active):
        return "Серверы настраиваются. Попробуйте через несколько минут."

    return "Готовим подключение, это займёт около минуты. Потяните экран, чтобы обновить."


def _serve_targets(
    db: OrmSession,
    user: User,
    device_id: str,
    background: BackgroundTasks | None = None,
) -> list[tuple[Server, UserKey | None]]:
    if not user.has_access():
        return []

    device_id = device_id or ""
    by_server: dict[int, UserKey] = {}
    shared: dict[int, UserKey] = {}
    for key in user.keys:
        if key.revoked_at is None:
            if is_ios_slot(key.device_id):
                continue
            if (key.device_id or "") == device_id:
                by_server[key.server_id] = key
            elif not key.device_id:
                shared[key.server_id] = key

    if background is not None:
        missing = any(
            server.id not in by_server and server.provisioning != Provisioning.SHARED
            for server in services.active_servers(db)
        )
        if missing:
            background.add_task(_provision_missing_keys, user.id, device_id)

    for server_id, key in shared.items():
        by_server.setdefault(server_id, key)

    targets: list[tuple[Server, UserKey | None]] = []
    for server in services.active_servers(db):
        if services.diagnostics.is_documentation_address(server.host):
            log.warning(
                "сервер «%s» пропущен: адрес %s из документационного диапазона",
                server.name,
                server.host,
            )
            continue
        targets.append((server, by_server.get(server.id)))
    return targets


def _servers_out(
    db: OrmSession,
    user: User,
    session: Session | None = None,
    background: BackgroundTasks | None = None,
) -> list[ServerOut]:
    device_id = session.device_key if session is not None else ""
    out: list[ServerOut] = []
    for server, key in _serve_targets(db, user, device_id, background):
        config = serving_config(server, key)
        if not config:
            continue
        main_port, spare_ports = _ports_for(db, server, key)
        config = _with_chosen_port(db, server, key, config)
        out.append(
            ServerOut(
                id=server.id,
                name=server.country or server.name,
                country=server.country,
                country_en=server.country_en or geo.country_en(server.country_code, server.country),
                city=server.city,
                city_en=server.city_en or server.city,
                country_code=server.country_code,
                config=config,
                alt_ports=[main_port] + spare_ports,
            )
        )
    return out


PORT_PROBE_SECONDS = 180

PORT_PROBE_GRACE = dt.timedelta(minutes=10)


def _ports_for(
    db: OrmSession, server: Server, key: UserKey | None
) -> tuple[int, list[int]]:
    if key is not None and key.endpoint_id is not None:
        endpoint = db.get(NodeEndpoint, key.endpoint_id)
        if endpoint is not None:
            return endpoint.listen_port, endpoint.alt_port_list()
    return server.port, server.alt_port_list()


def _with_chosen_port(
    db: OrmSession, server: Server, key: UserKey | None, config: str
) -> str:
    main_port, ports = _ports_for(db, server, key)
    if key is None or not ports:
        return config

    now = utcnow()
    if key.last_handshake_at is not None or now - key.created_at < PORT_PROBE_GRACE:
        chosen = key.endpoint_port or provisioning.endpoint_port(config) or main_port
        return provisioning.with_endpoint_port(config, chosen)

    wheel = [main_port] + ports
    index = int(now.timestamp() // PORT_PROBE_SECONDS) % len(wheel)
    chosen = wheel[index]
    if key.endpoint_port != chosen:
        key.endpoint_port = chosen
        db.commit()
    return provisioning.with_endpoint_port(config, chosen)


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
            ip=client_ip(request),
            device_id=body.device_id,
            device_name=body.device_name,
        )
    except services.LoginThrottled as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.retry_after), "X-Error-Code": "throttled"},
        ) from exc
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(exc), headers=_error_code_header(exc)
        ) from exc

    session = services.session_for_token(db, token)
    assert session is not None
    _provision_for_login(db, user, session)
    servers = _servers_out(db, user, session, background)
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
        subscription_url=_subscription_url(db, session),
    )


LOGIN_PROVISION_SECONDS = 8


def _provision_for_login(db: OrmSession, user: User, session: Session) -> None:
    if not user.has_access() or not session.is_device:
        return
    warnings = services.ensure_keys(
        db,
        user,
        devices={session.device_key},
        deadline=time.monotonic() + LOGIN_PROVISION_SECONDS,
    )
    for warning in warnings:
        log.warning("вход %s: %s", user.public_id, warning)

    db.expire(user, ["keys"])


class RegisterRequest(BaseModel):

    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=254)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=96)
    ref: str | None = Field(default=None, max_length=16)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    request: Request,
    background: BackgroundTasks,
    db: OrmSession = Depends(get_db),
) -> LoginResponse:
    config = settings()
    if not config.signup_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "регистрация сейчас закрыта",
            headers={"X-Error-Code": "signup_closed"},
        )

    ip = client_ip(request)
    verdict = services.ratelimit.hit(
        db,
        f"signup:{ip_tag(ip)}",
        limit=config.signup_max_per_ip,
        window_minutes=config.signup_window_minutes,
        lock_minutes=config.signup_window_minutes,
    )
    if not verdict.allowed:
        log.warning("регистрация заперта по частоте")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "с этого адреса уже заводили аккаунты — попробуйте позже",
            headers={"Retry-After": str(verdict.retry_after), "X-Error-Code": "throttled"},
        )

    try:
        user, _password, _warnings = services.create_user(
            db,
            login=body.login,
            password=body.password,
            plan_code=config.signup_plan_code,
            email=body.email,
            note="регистрация с сайта",
        )
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers=_error_code_header(exc)
        ) from exc

    if body.ref:
        try:
            services.referrals.register_from_site(db, body.ref, user)
        except Exception:
            db.rollback()
            log.exception("приглашение по коду %r не засчитано", body.ref)

    services.reset_login_throttle(db, body.login, ip)

    _user, token = services.authenticate(
        db,
        login=body.login,
        password=body.password,
        platform=body.platform,
        app_version=body.app_version,
        ip=ip,
        device_id=body.device_id,
        device_name=body.device_name,
    )
    session = services.session_for_token(db, token)
    assert session is not None
    _provision_for_login(db, user, session)
    servers = _servers_out(db, user, session, background)
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
        subscription_url=_subscription_url(db, session),
    )


@router.get("/servers", response_model=ServersResponse)
def servers(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> ServersResponse:
    services.touch(db, session, client_ip(request))
    user = session.user
    servers = _servers_out(db, user, session, background)
    return ServersResponse(
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
    )


@router.post("/heartbeat")
def heartbeat(
    request: Request,
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    services.touch(db, session, client_ip(request))
    user = session.user
    return {"ok": True, "active": user.has_access(), "subscription": _subscription_out(user).model_dump()}


class UpdateOut(BaseModel):

    update_available: bool
    version: str | None = None
    url: str | None = None
    changelog: str | None = None
    released_at: dt.datetime | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    mandatory: bool = False


@router.get("/version", response_model=UpdateOut)
def version(
    platform: str,
    current: str | None = None,
    db: OrmSession = Depends(get_db),
) -> UpdateOut:
    return UpdateOut(**services.check_update(db, platform, current))


@router.post("/logout")
def logout(
    session: Session = Depends(current_session), db: OrmSession = Depends(get_db)
) -> dict[str, bool]:
    session.revoked_at = services.utcnow()
    db.commit()
    return {"ok": True}


class RotateOut(BaseModel):
    subscription_url: str


@router.post("/subscription/rotate", response_model=RotateOut)
def subscription_rotate(
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> RotateOut:
    raw = services.subscription.rotate(
        db,
        session.user_id,
        session.device_key,
        label=session.device_name or session.platform,
    )
    return RotateOut(subscription_url=services.subscription.url_for(raw))
