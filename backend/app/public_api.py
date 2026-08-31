from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import payments, services
from .config import settings
from .db import get_db
from .models import (
    HANDSHAKE_WINDOW,
    IOS_MAX_KEYS,
    AppRelease,
    AuditLog,
    DeliveryJob,
    Order,
    OrderStatus,
    Plan,
    Session,
    SubscriptionToken,
    User,
    ios_slot_number,
    normalize_email,
    utcnow,
)
from .payments import platega
from .payments.base import WebhookRejected
from .security import client_ip, verify_password, ip_tag

log = logging.getLogger("panel.public")

router = APIRouter(prefix="/api/v1", tags=["site"])

EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$"


class PlanOut(BaseModel):

    code: str
    title: str
    tagline: str | None = None
    price_kopecks: int
    currency: str
    duration_days: int
    server_limit: int
    device_limit: int
    allowed_regions: list[str] | None = None
    traffic_limit_bytes: int | None = None
    purchasable: bool = True
    # Цена первой покупки. intro_applies говорит витрине, показывать её этому
    # человеку или обычную: вернувшемуся покупателю вводная уже не положена.
    intro_price_kopecks: int | None = None
    intro_applies: bool = False


def _plan_out(plan: Plan) -> PlanOut:
    return PlanOut(
        code=plan.code,
        title=plan.name,
        tagline=plan.tagline,
        price_kopecks=plan.price_kopecks,
        currency=plan.currency,
        duration_days=plan.period_days,
        server_limit=plan.server_limit,
        device_limit=plan.device_limit,
        allowed_regions=plan.allowed_regions,
        traffic_limit_bytes=plan.traffic_limit_bytes,
        purchasable=plan.price_kopecks > 0,
    )


@router.get("/plans", response_model=list[PlanOut])
def list_plans(
    request: Request,
    db: OrmSession = Depends(get_db),
) -> list[PlanOut]:
    # Кто спрашивает — знаем не всегда: страница тарифов открыта и гостю.
    # Гостю показываем вводную цену как есть: он ещё точно ничего не покупал.
    user = _optional_user(db, request)
    intro_ok = services.orders.intro_available(db, user, user.email_plain if user else None)

    out: list[PlanOut] = []
    for plan in services.site_plans(db):
        item = _plan_out(plan)
        if plan.intro_price_kopecks > 0:
            item.intro_price_kopecks = plan.intro_price_kopecks
            item.intro_applies = intro_ok
        out.append(item)
    return out


def _optional_user(db: OrmSession, request: Request) -> User | None:
    """Пользователь по токену, если он вообще прислан. Ошибку не поднимаем:
    список тарифов обязан открываться и без входа."""
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        return None
    try:
        session = services.session_for_token(db, token)
    except Exception:
        return None
    return session.user if session is not None else None


PaymentMethodIn = Literal["sbp", "card", "crypto", "sberpay", "ton"] | None


class OrderIn(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)
    quantity: int = 1
    platform: str | None = Field(default=None, max_length=16)
    payment_method: PaymentMethodIn = None


class OrderOut(BaseModel):
    id: str
    status: str
    plan_code: str
    amount_kopecks: int
    currency: str
    redirect_url: str | None = None
    created_at: dt.datetime
    payment_method: str | None = None


class OrderStatusOut(BaseModel):

    id: str
    status: str
    plan_code: str
    amount_kopecks: int
    currency: str = "RUB"
    is_renewal: bool = False
    login: str | None = None
    password: str | None = None
    expires_at: dt.datetime | None = None
    email: str | None = None


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: OrderIn, request: Request, db: OrmSession = Depends(get_db)
) -> OrderOut:
    ip = client_ip(request)
    verdict = services.ratelimit.hit(
        db, f"order:{ip_tag(ip)}", limit=settings().order_max_per_hour, window_minutes=60
    )
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "слишком много заказов с этого адреса, попробуйте позже",
            headers={"Retry-After": str(verdict.retry_after)},
        )

    try:
        order = services.create_order(
            db,
            plan_code=body.plan_code,
            email=str(body.email),
            quantity=body.quantity,
            ip=ip,
            platform=body.platform
            or services.orders.platform_from_user_agent(request.headers.get("user-agent")),
            payment_method=body.payment_method,
        )
    except services.OrderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return OrderOut(
        id=order.id,
        status=order.status,
        plan_code=order.plan_code,
        amount_kopecks=order.amount_kopecks,
        currency=order.currency,
        redirect_url=order.redirect_url,
        created_at=order.created_at,
        payment_method=order.payment_method,
    )


ORDER_PASSWORD_WINDOW = dt.timedelta(minutes=15)

PASSWORD_SHOWN_ACTION = "order.password_shown"


def _password_window_open(order: Order) -> bool:
    if order.paid_at is None:
        return False
    return utcnow() - order.paid_at <= ORDER_PASSWORD_WINDOW


@router.get("/orders/{order_id}/status", response_model=OrderStatusOut)
def order_status(
    order_id: str, response: Response, db: OrmSession = Depends(get_db)
) -> OrderStatusOut:
    response.headers["Cache-Control"] = "no-store"

    order = services.orders.find(db, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "заказ не найден")

    out = OrderStatusOut(
        id=order.id,
        status=order.status,
        plan_code=order.plan_code,
        amount_kopecks=order.amount_kopecks,
        currency=order.currency,
        is_renewal=order.is_renewal,
        email=order.email,
    )
    if order.status != OrderStatus.PAID.value or not order.user_id:
        return out

    user = db.get(User, order.user_id)
    if user is None:
        return out

    out.login = user.login
    out.expires_at = user.access_expires_at()

    if not order.is_renewal and _password_window_open(order):
        shown = db.scalar(
            select(AuditLog.id).where(
                AuditLog.action == PASSWORD_SHOWN_ACTION, AuditLog.target == order.id
            )
        )
        if shown is None:
            db.add(
                AuditLog(
                    admin_id=None,
                    action=PASSWORD_SHOWN_ACTION,
                    target=order.id,
                    detail=f"логин {user.login}",
                )
            )
            db.commit()
        try:
            out.password = services.reveal_password(user)
        except services.PanelError as exc:
            log.warning("пароль для страницы успеха недоступен: %s", exc)
    return out


@router.post("/billing/webhook/{provider_name}", include_in_schema=False)
async def billing_webhook(
    provider_name: str, request: Request, db: OrmSession = Depends(get_db)
) -> Response:
    raw_body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    ip = client_ip(request)

    try:
        payments.get(provider_name)
    except payments.UnknownProvider:
        log.warning("вебхук неизвестного провайдера %r с адреса %s", provider_name, ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "неизвестный провайдер") from None

    try:
        if provider_name == payments.PlategaProvider.name:
            platega.authenticate(headers)
            if platega.is_subscription_event(raw_body):
                result = services.recurring.handle_webhook(
                    db, headers=headers, raw_body=raw_body, client_ip=ip
                )
            else:
                result = services.billing_webhook.handle(
                    db, provider_name=provider_name, headers=headers, raw_body=raw_body, client_ip=ip
                )
        else:
            result = services.billing_webhook.handle(
                db, provider_name=provider_name, headers=headers, raw_body=raw_body, client_ip=ip
            )
    except WebhookRejected as exc:
        log.error("вебхук %s отклонён с адреса %s: %s", provider_name, ip, exc)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "подпись не подтверждена") from exc

    return Response(
        content=f'{{"result":"{result.result}"}}',
        media_type="application/json",
        status_code=result.http_status,
    )


class MockPayIn(BaseModel):
    order_id: str


@router.post("/billing/mock/pay", include_in_schema=False)
def mock_pay(body: MockPayIn, db: OrmSession = Depends(get_db)) -> dict[str, object]:
    if payments.active_name() != payments.MockProvider.name:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "не найдено")

    order = services.orders.find(db, body.order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "заказ не найден")
    if order.status != OrderStatus.PENDING.value:
        return {"ok": True, "status": order.status}

    from .payments.mock import dispatch

    dispatch(order.id, "succeeded")
    return {"ok": True, "status": order.status}


def current_user(
    request: Request, db: OrmSession = Depends(get_db)
) -> tuple[User, Session]:
    authorization = request.headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен токен")
    session = services.session_for_token(db, authorization.split(" ", 1)[1].strip())
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен недействителен")
    return session.user, session


class DeviceOut(BaseModel):
    id: int
    kind: str = "app"
    slot: int | None = None
    name: str | None = None
    platform: str | None = None
    app_version: str | None = None
    last_seen_at: dt.datetime
    created_at: dt.datetime
    is_current: bool = False
    is_connected: bool = False


class PaymentOut(BaseModel):
    amount: float
    currency: str = "RUB"
    comment: str | None = None
    paid_at: dt.datetime


class IosKeyOut(BaseModel):

    slot: int
    name: str
    server_id: int
    server: str
    country: str | None = None
    country_code: str | None = None
    city: str | None = None
    vpn_url: str
    qr_payload: str | None = None
    traffic_bytes: int = 0
    last_handshake_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    is_connected: bool = False
    disconnected: bool = False


class ReferralFriendOut(BaseModel):

    joined_at: dt.datetime
    days: int
    paid: bool
    pending: bool


class ReferralsOut(BaseModel):
    linked: bool = False
    invite_url: str | None = None
    site_url: str = ""
    bot_url: str = ""
    days_total: int = 0
    invited: int = 0
    purchased: int = 0
    pending: int = 0
    join_days: int = 0
    purchase_days: int = 0
    friends: list[ReferralFriendOut] = []


class IosServerOut(BaseModel):

    id: int
    name: str
    country: str | None = None
    country_code: str | None = None
    city: str | None = None


class IosOut(BaseModel):
    available: bool = False
    blocked: bool = False
    keys: list[IosKeyOut] = []
    disconnected_keys: list[IosKeyOut] = []
    max_keys: int = IOS_MAX_KEYS
    keys_count: int = 0
    can_add: bool = False
    servers: list[IosServerOut] = []
    guide_url: str | None = None
    notice: str | None = None


class TunnelFileOut(BaseModel):

    available: bool = False
    filename: str | None = None
    version: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    note: str | None = None
    updated_at: dt.datetime | None = None
    url: str = "/api/v1/tunnel-file/download"


class UpcomingOut(BaseModel):

    plan: str
    plan_title: str | None = None
    starts_at: dt.datetime
    expires_at: dt.datetime
    period_days: int


class FreezeOut(BaseModel):
    """Пауза подписки — состояние и право её поставить."""

    frozen: bool = False
    frozen_at: dt.datetime | None = None
    frozen_days: int = 0
    # Остаток на момент паузы: он и есть главное число этой карточки — дни,
    # которые дожидаются возвращения.
    days_left: int | None = None
    resumes_by: dt.datetime | None = None
    can_freeze: bool = False
    # Почему нельзя — готовым текстом: витрины показывают его как есть.
    reason: str = ""
    max_days: int = 0
    used_days: int = 0
    count: int = 0
    per_month: int = 0
    month_left: int = 0


class AccountOut(BaseModel):
    login: str
    email: str | None = None
    public_id: str
    plan: str | None = None
    plan_title: str | None = None
    period_days: int | None = None
    price: float | None = None
    active: bool
    expires_at: dt.datetime | None = None
    days_left: int | None = None
    expires_total_at: dt.datetime | None = None
    upcoming: list[UpcomingOut] = []
    device_limit: int
    devices: list[DeviceOut]
    traffic_used_bytes: int = 0
    traffic_limit_bytes: int | None = None
    payments: list[PaymentOut] = []
    ios: IosOut = IosOut()
    tunnel_file: TunnelFileOut = TunnelFileOut()
    freeze: FreezeOut = FreezeOut()


def _device_connected(user: User, device_id: str, now: dt.datetime) -> bool:
    for key in user.keys:
        if key.revoked_at is not None or (key.device_id or "") != device_id:
            continue
        if key.last_handshake_at is not None and key.last_handshake_at > now - HANDSHAKE_WINDOW:
            return True
    return False


def _ios_out(db: OrmSession, user: User, now: dt.datetime) -> IosOut:
    servers = [
        IosServerOut(
            id=server.id,
            name=server.name,
            country=server.country,
            country_code=server.country_code,
            city=server.city,
        )
        for server in services.ios.choices(db)
    ]

    if not user.ios_access:
        return IosOut(available=False, servers=servers, guide_url=settings().guide_link)

    if user.ios_blocked:
        return IosOut(
            available=True,
            blocked=True,
            guide_url=settings().guide_link,
            notice="Ключи отключены. Напишите в поддержку — разберёмся, в чём дело.",
        )

    def key_out(key: "services.ios.IosKey") -> IosKeyOut:
        return IosKeyOut(
            slot=key.slot,
            name=key.name,
            server_id=key.server_id,
            server=key.country or key.server_name,
            country=key.country,
            country_code=key.country_code,
            city=key.city,
            vpn_url=key.vpn_url,
            qr_payload=key.qr_payload,
            traffic_bytes=key.traffic_bytes,
            last_handshake_at=key.last_handshake_at,
            created_at=key.created_at,
            is_connected=(
                key.last_handshake_at is not None
                and key.last_handshake_at > now - HANDSHAKE_WINDOW
            ),
            disconnected=key.disconnected,
        )

    everything = services.ios.keys(user, include_disconnected=True)
    keys = [key_out(k) for k in everything if k.is_active]
    off = [key_out(k) for k in everything if not k.is_active and k.disconnected]

    notice = None
    if not keys and not off:
        if not user.has_access(now):
            notice = "Ключи отключены: подписка кончилась или закрыт доступ."
        else:
            notice = "Готовим ключи, это займёт около минуты — обновите страницу."

    used = len({key.slot for key in keys} | {key.slot for key in off})
    return IosOut(
        available=True,
        keys=keys,
        disconnected_keys=off,
        max_keys=IOS_MAX_KEYS,
        keys_count=used,
        can_add=user.has_access(now) and services.ios.free_slot(user) is not None,
        servers=servers,
        guide_url=settings().guide_link,
        notice=notice,
    )


def _ios_device_rows(user: User, now: dt.datetime) -> list[DeviceOut]:
    by_slot: dict[int, list] = {}
    for key in user.keys:
        number = ios_slot_number(key.device_id)
        if number > 0 and key.revoked_at is None:
            by_slot.setdefault(number, []).append(key)

    rows: list[DeviceOut] = []
    for number, slot_keys in sorted(by_slot.items()):
        stamps = [k.last_handshake_at for k in slot_keys if k.last_handshake_at is not None]
        if not stamps:
            continue
        last = max(stamps)
        rows.append(
            DeviceOut(
                id=-number,
                kind="ios_key",
                slot=number,
                platform="amnezia",
                last_seen_at=last,
                created_at=min(k.created_at for k in slot_keys),
                is_connected=last > now - HANDSHAKE_WINDOW,
            )
        )
    return rows


def _tunnel_out(db: OrmSession) -> TunnelFileOut:
    entry = services.tunnel.current(db)
    if entry is None:
        return TunnelFileOut(available=False)
    return TunnelFileOut(
        available=True,
        filename=entry.filename,
        version=entry.version,
        size_bytes=entry.size_bytes,
        sha256=entry.sha256,
        note=entry.note,
        updated_at=entry.updated_at,
    )


def _account_out(db: OrmSession, user: User, current: Session) -> AccountOut:
    subscription = user.active_subscription()
    plan = subscription.plan_ref if subscription else None
    now = utcnow()

    devices = [
        DeviceOut(
            id=session.id,
            name=session.device_name,
            platform=session.platform,
            app_version=session.app_version,
            last_seen_at=session.last_seen_at,
            created_at=session.created_at,
            is_current=session.id == current.id,
            is_connected=_device_connected(user, session.device_key, now),
        )
        for session in user.device_sessions(now)
    ] + _ios_device_rows(user, now)
    devices.sort(key=lambda d: d.last_seen_at, reverse=True)

    return AccountOut(
        login=user.login,
        email=user.email_plain,
        public_id=user.public_id,
        plan=subscription.plan if subscription else None,
        plan_title=plan.name if plan else None,
        period_days=plan.period_days if plan else None,
        price=float(subscription.price) if subscription and subscription.price else None,
        active=user.has_access(now),
        # Дата показывается «как если бы разморозили сейчас»: у замороженной
        # подписки в базе лежит старый срок, он уже прошёл, и показывать его
        # человеку нельзя — он решит, что дни сгорели.
        expires_at=user.access_ends_if_resumed(now),
        days_left=user.access_days_left_display(now),
        expires_total_at=user.access_ends_if_resumed(now),
        upcoming=[
            UpcomingOut(
                plan=s.plan,
                plan_title=s.plan_ref.name if s.plan_ref else s.plan,
                starts_at=s.starts_at,
                expires_at=s.expires_at,
                period_days=s.period_days,
            )
            for s in user.upcoming_subscriptions(now)
        ],
        device_limit=user.device_limit(now),
        devices=devices,
        traffic_used_bytes=user.traffic_used_bytes,
        traffic_limit_bytes=user.effective_traffic_limit(now),
        payments=[
            PaymentOut(
                amount=float(payment.amount),
                currency=payment.currency,
                comment=payment.comment,
                paid_at=payment.paid_at,
            )
            for payment in sorted(user.payments, key=lambda p: p.paid_at, reverse=True)
        ],
        ios=_ios_out(db, user, now),
        tunnel_file=_tunnel_out(db),
        freeze=FreezeOut(**services.freeze.state(user, now)),
    )


@router.get("/account", response_model=AccountOut)
def account(
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    user, session = who
    response.headers["Cache-Control"] = "no-store"
    return _account_out(db, user, session)


class IosCreateIn(BaseModel):

    server_id: int | None = None


@router.get("/account/referrals", response_model=ReferralsOut)
def account_referrals(
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> ReferralsOut:
    user, _ = who
    response.headers["Cache-Control"] = "no-store"

    config = settings()
    data = services.referrals.for_account(db, user)
    bot = config.telegram_bot_username
    telegram_id = data.pop("telegram_id", None)
    code = data.pop("code")
    invite = f"https://t.me/{bot}?start=ref{telegram_id}" if telegram_id else None
    site = f"{config.site_url.rstrip('/')}/?ref={code}"
    return ReferralsOut(
        **data, invite_url=invite, site_url=site, bot_url=f"https://t.me/{bot}"
    )


@router.post("/account/ios", response_model=AccountOut)
def enable_ios(
    response: Response,
    body: IosCreateIn = IosCreateIn(),
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    if user.ios_blocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "ключ отключён — напишите в поддержку",
            headers={"X-Error-Code": "ios_blocked"},
        )

    if not user.has_access():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ключ выдаётся по действующей подписке — оплатите тариф",
            headers={"X-Error-Code": "no_subscription"},
        )

    try:
        if not user.ios_access:
            warnings = services.ios.enable(db, user, server_id=body.server_id)
        elif not services.ios.keys(user):
            warnings = services.ios.sync(db, user, home=services.ios.home_id(db, body.server_id))
        else:
            warnings = []
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_add_failed"}
        ) from exc

    for warning in warnings:
        log.warning("ключ AmneziaVPN для %s: %s", user.public_id, warning)
    return _account_out(db, user, session)


@router.post("/account/freeze", response_model=AccountOut)
def freeze_subscription(
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    """
    Ставит подписку на паузу: дни перестают тратиться, доступ закрывается.

    Право на паузу проверяет сервис, а не эта ручка: те же правила нужны
    панели и боту, и разъезжаться им нельзя.
    """
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    try:
        problems = services.freeze.freeze(db, user, by="кабинет")
    except services.FreezeError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": exc.code}
        ) from exc

    for problem in problems:
        log.warning("пауза %s: доступ остался на узле — %s", user.public_id, problem)

    return _account_out(db, user, session)


@router.post("/account/resume", response_model=AccountOut)
def resume_subscription(
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    """Снимает паузу и возвращает подписке простоявшее время."""
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    services.freeze.resume(db, user, by="кабинет")

    return _account_out(db, user, session)


@router.post("/account/ios/keys", response_model=AccountOut)
def add_ios_key(
    response: Response,
    body: IosCreateIn = IosCreateIn(),
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    try:
        number, warnings = services.ios.add_key(db, user, server_id=body.server_id)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_add_failed"}
        ) from exc

    for warning in warnings:
        log.warning("ключ %s AmneziaVPN для %s: %s", number, user.public_id, warning)
    return _account_out(db, user, session)


@router.delete("/account/ios/keys/{slot}", response_model=AccountOut)
def delete_ios_key(
    slot: int,
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    try:
        problems = services.ios.remove_key(db, user, slot)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_remove_failed"}
        ) from exc

    for problem in problems:
        log.warning("ключ %s AmneziaVPN для %s: %s", slot, user.public_id, problem)
    return _account_out(db, user, session)


@router.post("/account/ios/keys/{slot}/disconnect", response_model=AccountOut)
def disconnect_ios_key(
    slot: int,
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    try:
        problems = services.ios.disconnect_key(db, user, slot)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_off_failed"}
        ) from exc

    for problem in problems:
        log.warning("отключение ключа %s у %s: %s", slot, user.public_id, problem)
    return _account_out(db, user, session)


@router.post("/account/ios/keys/{slot}/enable", response_model=AccountOut)
def enable_ios_key(
    slot: int,
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    if user.ios_blocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "ключ отключён — напишите в поддержку",
            headers={"X-Error-Code": "ios_blocked"},
        )

    try:
        warnings = services.ios.reconnect_key(db, user, slot)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_on_failed"}
        ) from exc

    for warning in warnings:
        log.warning("включение ключа %s у %s: %s", slot, user.public_id, warning)
    return _account_out(db, user, session)


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetIn(BaseModel):
    token: str = Field(min_length=8, max_length=256)
    password: str = Field(min_length=8, max_length=128)


class ResetCheckOut(BaseModel):
    valid: bool
    login: str | None = None


@router.post("/password/forgot")
def password_forgot(
    body: ForgotIn, request: Request, db: OrmSession = Depends(get_db)
) -> dict[str, object]:
    ip = client_ip(request)
    verdict = services.ratelimit.hit(
        db, f"forgot:{ip}", limit=5, window_minutes=60, lock_minutes=60
    )
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "слишком много попыток — попробуйте через час",
            headers={"Retry-After": str(verdict.retry_after or 3600)},
        )

    address = normalize_email(body.email)
    try:
        services.passwords.request(db, address, ip=ip)
    except Exception:
        log.exception("сброс пароля: не удалось подготовить письмо")

    return {"ok": True}


@router.get("/password/reset/{token}", response_model=ResetCheckOut)
def password_reset_check(token: str, db: OrmSession = Depends(get_db)) -> ResetCheckOut:
    entry = services.passwords.find(db, token)
    if entry is None:
        return ResetCheckOut(valid=False)
    return ResetCheckOut(valid=True, login=entry.user.login)


@router.post("/password/reset")
def password_reset(body: ResetIn, db: OrmSession = Depends(get_db)) -> dict[str, object]:
    try:
        user = services.passwords.apply(db, body.token, body.password)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "reset_failed"}
        ) from exc
    return {"ok": True, "login": user.login}


def _issued_password(user: User) -> str | None:
    """Выданный пароль в открытом виде — или ничего, если ключ шифрования
    недоступен. Молчим, а не роняем профиль: без пароля экран всё равно
    полезен, там есть логин и кнопка «задать свои»."""
    if not user.password_enc:
        return None
    try:
        return services.delivery._password(user)
    except Exception:
        return None


# Сколько ссылок-подписок человек может держать разом. Пять — это телефон,
# планшет, ноутбук, телевизор и запас; больше обычно значит, что ссылку
# раздали, а не расставили по своим устройствам.
MAX_SUBSCRIPTION_KEYS = 5

# Слот ссылки, выпущенной руками. Отличает её от подписок, которые наши
# приложения заводят себе сами по идентификатору устройства.
EXTERNAL_SLOT_PREFIX = "ext-"


class SubscriptionKeyOut(BaseModel):
    """Одна выпущенная ссылка-подписка."""

    id: int
    label: str | None = None
    url: str | None = None
    # Одна и та же ссылка отдаёт оба формата — приложение выбирает себя по
    # User-Agent. Но когда её вставляют руками, угадывать нечем, поэтому
    # рядом лежат две с явным параметром: какая куда, видно по названию.
    url_amnezia: str | None = None
    url_vless: str | None = None
    created_at: dt.datetime
    last_used_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    is_secret_shown: bool = False


class SubscriptionKeyIn(BaseModel):
    label: str | None = Field(default=None, max_length=64)


def _key_out(tok, raw: str | None) -> SubscriptionKeyOut:
    """Одна ссылка в ответе. raw пуст — значит показать нечего."""
    base = services.subscription.url_for(raw) if raw else None
    return SubscriptionKeyOut(
        id=tok.id,
        label=tok.label,
        url=base,
        url_amnezia=(f"{base}?format=amnezia" if base else None),
        url_vless=(f"{base}?format=vless" if base else None),
        created_at=tok.created_at,
        last_used_at=tok.last_used_at,
        expires_at=tok.expires_at,
        is_secret_shown=bool(base),
    )


class CredentialsOut(BaseModel):
    login: str
    # Пароль отдаём, только пока он выданный: человек его не видел, а другого
    # способа узнать у него нет. Свой пароль обратно не показываем никогда.
    password: str | None = None
    is_generated: bool = True


class CredentialsIn(BaseModel):
    login: str | None = Field(default=None, min_length=3, max_length=64)
    password: str | None = Field(default=None, min_length=8, max_length=128)


@router.get("/account/credentials", response_model=CredentialsOut)
def account_credentials(
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> CredentialsOut:
    """Данные для входа на сайт. В мини-приложении они не нужны — оно
    открывается по подписи Telegram, — но с компьютера зайти нечем."""
    user, _session = who
    generated = user.credentials_set_at is None
    return CredentialsOut(
        login=user.login,
        password=(_issued_password(user) if generated else None),
        is_generated=generated,
    )


@router.get("/account/subscriptions", response_model=list[SubscriptionKeyOut])
def subscription_keys(
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> list[SubscriptionKeyOut]:
    """
    Ссылки-подписки для сторонних приложений — вместе с самими ссылками.

    Раньше ссылка показывалась один раз: в базе лежал только хэш. Экран
    установки теперь держит её на виду постоянно, поэтому рядом с хэшем
    хранится шифротекст (token_enc). У ссылок, выпущенных до этого, его нет
    — они вернутся без url, и человеку останется выпустить новую.

    Первую ссылку заводим сами: человек пришёл на экран установки не для
    того, чтобы нажать «создать», а чтобы взять ключ.
    """
    user, _session = who

    mine = [
        tok
        for tok in services.subscription.active_for_user(db, user.id)
        if (tok.device_id or "").startswith(EXTERNAL_SLOT_PREFIX)
    ]
    if not mine:
        services.subscription.mint(db, user.id, f"{EXTERNAL_SLOT_PREFIX}1", label=None)
        mine = [
            tok
            for tok in services.subscription.active_for_user(db, user.id)
            if (tok.device_id or "").startswith(EXTERNAL_SLOT_PREFIX)
        ]

    return [_key_out(tok, services.subscription.reveal(tok)) for tok in mine]


@router.post("/account/subscriptions", response_model=SubscriptionKeyOut, status_code=status.HTTP_201_CREATED)
def issue_subscription_key(
    body: SubscriptionKeyIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> SubscriptionKeyOut:
    """
    Выпускает ссылку под одно устройство.

    Слот занимает не настоящий идентификатор устройства, а свой — «ext-N»:
    стороннее приложение о себе ничего не сообщает, и связать ссылку с
    железкой нельзя. Человек сам подписывает, куда её поставил.
    """
    user, _session = who

    # Считаем только свои слоты. Наши приложения выпускают подписку каждому
    # устройству само, и если мешать их в общий счёт, человек упрётся в предел,
    # не создав ни одной ссылки руками.
    existing = [
        tok
        for tok in services.subscription.active_for_user(db, user.id)
        if (tok.device_id or "").startswith(EXTERNAL_SLOT_PREFIX)
    ]
    if len(existing) >= MAX_SUBSCRIPTION_KEYS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"уже выпущено {len(existing)} ссылок — отзовите ненужную",
            headers={"X-Error-Code": "too_many_keys"},
        )

    taken = {tok.device_id for tok in existing}
    slot = next(
        (
            f"{EXTERNAL_SLOT_PREFIX}{n}"
            for n in range(1, MAX_SUBSCRIPTION_KEYS + 1)
            if f"{EXTERNAL_SLOT_PREFIX}{n}" not in taken
        ),
        None,
    )
    if slot is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "свободных слотов не осталось")

    label = (body.label or "").strip()[:64] or None
    raw = services.subscription.mint(db, user.id, slot, label=label)

    tok = services.subscription.resolve(db, raw)
    assert tok is not None
    return _key_out(tok, raw)


@router.delete("/account/subscriptions/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_subscription_key(
    key_id: int,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> Response:
    """
    Отзывает ссылку. Приложения, куда её вставили, перестанут получать ключи.
    """
    user, _session = who
    tok = db.get(SubscriptionToken, key_id)
    if (
        tok is None
        or tok.user_id != user.id
        or tok.revoked_at is not None
        or not (tok.device_id or "").startswith(EXTERNAL_SLOT_PREFIX)
    ):
        # Чужую и служебную не трогаем: подписку своего приложения человек
        # отзывает отвязкой устройства, а не отсюда.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ссылка не найдена")

    tok.revoked_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/account/credentials", response_model=CredentialsOut)
def account_credentials_set(
    body: CredentialsIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> CredentialsOut:
    """
    Задать свои логин и пароль.

    Текущий пароль не спрашиваем, пока он выданный: человек его не выбирал и
    может не знать. Как только свои данные заданы, смена пароля идёт обычным
    путём — через /account/password с подтверждением старого.
    """
    user, _session = who
    if user.credentials_set_at is not None and body.password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "пароль уже задан — меняйте его в разделе смены пароля",
            headers={"X-Error-Code": "password_already_set"},
        )
    if not body.login and not body.password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "нечего менять",
            headers={"X-Error-Code": "empty"},
        )

    if body.login:
        login = body.login.strip()
        if not all(ch.isascii() and (ch.isalnum() or ch in "-_.") for ch in login):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "в логине допустимы латинские буквы, цифры, дефис, точка и подчёркивание",
                headers={"X-Error-Code": "login_invalid"},
            )
        taken = db.scalar(select(User).where(User.login == login, User.id != user.id).limit(1))
        if taken is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "такой логин уже занят",
                headers={"X-Error-Code": "login_taken"},
            )
        user.login = login

    if body.password:
        # set_password гасит остальные сессии; текущую оставляем — человек
        # только что был здесь, выкидывать его из приложения незачем.
        services.set_password(db, user, body.password)
        user.credentials_set_at = utcnow()

    db.commit()
    db.refresh(user)
    generated = user.credentials_set_at is None
    return CredentialsOut(
        login=user.login,
        password=(_issued_password(user) if generated else None),
        is_generated=generated,
    )


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/account/password")
def change_password(
    body: PasswordChangeIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    user, session = who
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "текущий пароль неверен")

    services.set_password(db, user, body.new_password)
    return {"ok": True, "relogin_required": True}


class EmailIn(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)


@router.post("/account/email")
def set_account_email(
    body: EmailIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    user, _ = who
    address = normalize_email(body.email)

    taken = services.find_by_email(db, address)
    if taken is not None and taken.id != user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "эта почта уже привязана к другой учётке",
            headers={"X-Error-Code": "email_taken"},
        )

    previous = user.email_plain
    user.set_email(address)

    if address and address != previous:
        db.add(
            DeliveryJob(
                channel="email",
                template="email_attached",
                target=address,
                user_id=user.id,
            )
        )

    db.commit()
    return {"ok": True, "email": address}


@router.delete("/account/devices/{device_id}")
def unlink_device(
    device_id: int,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    user, _ = who
    problems = services.disconnect_device_by_id(db, user, device_id)
    if problems is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "устройство не найдено")
    return {"ok": True, "problems": problems}


class RenewIn(BaseModel):
    plan_code: str | None = None
    quantity: int = 1
    payment_method: PaymentMethodIn = None


@router.post("/account/renew", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def renew(
    body: RenewIn,
    request: Request,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> OrderOut:
    user, _ = who

    plan_code = body.plan_code
    if not plan_code:
        subscription = user.active_subscription()
        plan_code = subscription.plan if subscription else None
    if not plan_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "выберите тариф")

    try:
        order = services.create_order_for_user(
            db,
            user,
            plan_code=plan_code,
            origin="site",
            quantity=body.quantity,
            ip=client_ip(request),
            platform=(
                "ios"
                if user.ios_access
                else services.orders.platform_from_user_agent(request.headers.get("user-agent"))
            ),
            payment_method=body.payment_method,
        )
    except services.OrderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return OrderOut(
        id=order.id,
        status=order.status,
        plan_code=order.plan_code,
        amount_kopecks=order.amount_kopecks,
        currency=order.currency,
        redirect_url=order.redirect_url,
        created_at=order.created_at,
        payment_method=order.payment_method,
    )


@router.get("/tunnel-file", response_model=TunnelFileOut)
def tunnel_file(db: OrmSession = Depends(get_db)) -> TunnelFileOut:
    return _tunnel_out(db)


@router.get("/tunnel-file/download", include_in_schema=False)
def tunnel_file_download(db: OrmSession = Depends(get_db)) -> Response:
    entry = services.tunnel.current(db)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "файл ещё не загружен")

    media = "application/json" if entry.filename.lower().endswith(".json") else "text/plain"
    return Response(
        content=entry.content,
        media_type=f"{media}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{entry.filename}"',
            "Cache-Control": "no-cache",
        },
    )


class TransferIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=255)
    days: int = Field(ge=1, le=3650)
    note: str | None = Field(default=None, max_length=160)


class TransferOut(BaseModel):

    id: int
    days: int
    direction: str
    counterpart: str
    created_at: dt.datetime
    note: str | None = None


def _transfer_out(record, user: User, db: OrmSession) -> TransferOut:
    outgoing = record.from_user_id == user.id
    other = db.get(User, record.to_user_id if outgoing else record.from_user_id)
    return TransferOut(
        id=record.id,
        days=record.days,
        direction="sent" if outgoing else "received",
        counterpart=other.public_id if other else "—",
        created_at=record.created_at,
        note=record.note,
    )


@router.get("/account/transfers", response_model=list[TransferOut])
def transfers_history(
    who: tuple[User, Session] = Depends(current_user), db: OrmSession = Depends(get_db)
) -> list[TransferOut]:
    user, _ = who
    return [_transfer_out(row, user, db) for row in services.transfers.history(db, user)]


@router.post("/account/transfers", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
def transfer_days(
    body: TransferIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> TransferOut:
    user, _ = who
    verdict = services.ratelimit.hit(
        db,
        f"transfer:{user.id}",
        limit=settings().order_max_per_hour,
        window_minutes=60,
    )
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "слишком много переводов подряд — попробуйте позже",
        )
    try:
        record = services.transfers.transfer(
            db, user, body.recipient, body.days, origin="site", note=body.note
        )
    except services.transfers.TransferError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return _transfer_out(record, user, db)


class RecurringPlanOut(BaseModel):

    code: str
    title: str
    amount_kopecks: int
    currency: str
    interval: str


class RecurringOut(BaseModel):

    status: str | None = None
    plan_code: str | None = None
    plan_title: str | None = None
    amount_kopecks: int | None = None
    currency: str | None = None
    interval: str | None = None
    next_charge_at: dt.datetime | None = None
    last_charge_error: str | None = None
    redirect_url: str | None = None
    available: list[RecurringPlanOut] = []


def _recurring_out(db: OrmSession, user: User) -> RecurringOut:
    sub = services.recurring.get_live(db, user)
    plans_by_code = {plan.code: plan for plan in services.site_plans(db)}
    available = [
        RecurringPlanOut(
            code=plan.code,
            title=plan.name,
            amount_kopecks=plan.price_kopecks,
            currency=plan.currency,
            interval=services.recurring.plan_interval(plan) or "month",
        )
        for plan in services.recurring.eligible_plans(db)
    ]
    if sub is None:
        return RecurringOut(available=available)
    plan = plans_by_code.get(sub.plan_code)
    return RecurringOut(
        status=sub.status,
        plan_code=sub.plan_code,
        plan_title=plan.name if plan else sub.plan_code,
        amount_kopecks=sub.amount_kopecks,
        currency=sub.currency,
        interval=sub.interval,
        next_charge_at=sub.next_charge_at,
        last_charge_error=sub.last_charge_error,
        redirect_url=sub.redirect_url if sub.status == "pending" else None,
        available=available,
    )


@router.get("/account/recurring", response_model=RecurringOut)
def recurring_status(
    who: tuple[User, Session] = Depends(current_user), db: OrmSession = Depends(get_db)
) -> RecurringOut:
    user, _ = who
    return _recurring_out(db, user)


class RecurringIn(BaseModel):
    plan_code: str


@router.post("/account/recurring", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
def recurring_create(
    body: RecurringIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> RecurringOut:
    user, _ = who
    try:
        sub = services.recurring.create(db, user, body.plan_code, origin="site")
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    out = _recurring_out(db, user)
    out.redirect_url = sub.redirect_url
    return out


@router.post("/account/recurring/cancel", response_model=RecurringOut)
def recurring_cancel(
    who: tuple[User, Session] = Depends(current_user), db: OrmSession = Depends(get_db)
) -> RecurringOut:
    user, _ = who
    sub = services.recurring.get_live(db, user)
    if sub is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "автосписание не подключено")
    try:
        services.recurring.cancel(db, sub)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _recurring_out(db, user)


class DownloadOut(BaseModel):
    platform: str
    version: str
    url: str
    size_bytes: int | None = None
    released_at: dt.datetime


@router.get("/downloads", response_model=list[DownloadOut])
def downloads(db: OrmSession = Depends(get_db)) -> list[DownloadOut]:
    out: list[DownloadOut] = []
    for platform in ("windows", "android", "ios", "macos", "linux"):
        release: AppRelease | None = services.latest_for(db, platform)
        if release is None:
            continue
        out.append(
            DownloadOut(
                platform=platform,
                version=release.version,
                url=release.url,
                size_bytes=release.size_bytes,
                released_at=release.released_at,
            )
        )
    return out
