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
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from . import services
from .config import settings
from .db import get_db
from .models import Provisioning, Session, User
from .provisioning import config_for
from .security import client_ip

log = logging.getLogger("panel.client")

router = APIRouter(prefix="/api/v1", tags=["client"])


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    # Постоянный идентификатор установки. Нужен, чтобы лимит устройств
    # считал переустановку приложения тем же телефоном, а не вторым.
    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=96)


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

    # Остаток трафика. None — безлимит. Считает сервер, а не приложение:
    # вычитание в клиенте однажды разойдётся с тем, по чему реально
    # закрывается доступ.
    traffic_left_bytes: int | None = None
    # Осталось меньше десятой части лимита — приложению пора предупредить.
    traffic_low: bool = False

    # Подписка кончается в ближайшие дни: приложению пора показать кнопку
    # продления. Порог задаёт сервер, чтобы менять его без пересборки
    # приложений на четырёх платформах.
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
    # Почему список пуст. Пустой массив без объяснения — худшее, что может
    # показать приложение: человек ввёл логин с паролем, вошёл, и дальше
    # тишина. См. _notice_for.
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


# Меньше этой доли лимита — приложение показывает предупреждение. Десятая
# часть выбрана так, чтобы у человека оставалось время продлить, а не чтобы
# он узнал об окончании в момент отключения.
TRAFFIC_LOW_FRACTION = 0.1

# За сколько дней до конца подписки приложение показывает кнопку продления.
EXPIRES_SOON_DAYS = 3


def _subscription_out(user: User) -> SubscriptionOut:
    sub = user.active_subscription()
    limit = user.effective_traffic_limit()
    used = user.traffic_used_bytes

    left_bytes = max(0, limit - used) if limit is not None else None
    traffic_low = left_bytes is not None and left_bytes <= limit * TRAFFIC_LOW_FRACTION

    if sub is None:
        return SubscriptionOut(
            active=False,
            traffic_used_bytes=used,
            traffic_limit_bytes=limit,
            traffic_left_bytes=left_bytes,
            traffic_low=traffic_low,
            # Подписки нет вовсе — продление нужно тем более.
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
        renew_url=_renew_url() if expires_soon else None,
    )


def _renew_url() -> str:
    """
    Куда приложение отправляет человека продлевать.

    В личный кабинет, а не сразу на оплату: там он войдёт теми же логином и
    паролем, увидит свой тариф и срок и нажмёт «Продлить». Ссылка прямо на
    платёжную форму потребовала бы заводить заказ до того, как человек
    вообще решил платить.
    """
    return f"{settings().site_url.rstrip('/')}/account.html"


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


def _notice_for(db: OrmSession, user: User, servers: list[ServerOut]) -> str | None:
    """
    Почему приложению нечего показать.

    Пустой список без объяснения — это и был весь баг: человек оплачивал,
    вводил логин с паролем, входил успешно и упирался в пустой экран. Ни
    приложение, ни панель не могли сказать, в чём дело, потому что API
    отдавал `[]` и не отдавал причины.

    Текст пишется для человека и показывается им как есть, поэтому он
    объясняет, что делать, а не что сломалось внутри.
    """
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
        # Ни одного включённого узла. Это не проблема клиента: сервис не
        # доделан или узлы выключены администратором.
        return "Серверы временно недоступны. Мы уже занимаемся этим — попробуйте позже."

    if not any(services.can_serve(server) for server in active):
        # Узлы есть, но выдать с них нечего: нет шаблона, нет общего ключа
        # либо адрес демонстрационный. Клиенту знать подробности незачем.
        return "Серверы настраиваются. Попробуйте через несколько минут."

    # Узлы рабочие, а конфига именно для этого человека ещё нет — обычно так
    # выглядят первые секунды после оплаты, пока пиры создаются в фоне.
    return "Готовим подключение, это займёт около минуты. Потяните экран, чтобы обновить."


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
        if services.diagnostics.is_documentation_address(server.host):
            # Адрес из диапазона для примеров в документации — подключаться
            # там не к чему. Такой узел попадает в базу только из
            # демонстрационных данных, и отдать его клиенту хуже, чем не
            # отдать ничего: он увидит страну в списке, нажмёт «подключиться»
            # и получит вечное ожидание вместо понятной ошибки.
            log.warning(
                "сервер «%s» пропущен: адрес %s из документационного диапазона",
                server.name,
                server.host,
            )
            continue

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
            ip=client_ip(request),
            device_id=body.device_id,
            device_name=body.device_name,
        )
    except services.LoginThrottled as exc:
        # 429, а не 401: приложению нужно понять, что дело не в пароле, и
        # не предлагать человеку набрать его ещё раз прямо сейчас.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    session = services.session_for_token(db, token)
    assert session is not None
    servers = _servers_out(db, user, background)
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
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
    servers = _servers_out(db, user, background)
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
    """Приложение отмечается, пока подключено — из этого видно живые сессии."""
    services.touch(db, session, client_ip(request))
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
