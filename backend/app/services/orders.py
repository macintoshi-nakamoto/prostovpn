from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .. import crypto, payments
from ..payments import platega
from ..config import settings
from ..models import (
    AuditLog,
    Order,
    OrderStatus,
    Plan,
    Subscription,
    User,
    normalize_email,
    utcnow,
)
from ..security import hash_password
from . import credentials, users
from .billing import grant_subscription
from .errors import PanelError

log = logging.getLogger("panel.orders")


class OrderError(PanelError):
    pass


LINK_FRESH_MINUTES = 10
LINK_SAFETY_MINUTES = 3


def normalize_payment_method(name: str | None) -> str | None:
    cleaned = (name or "").strip().lower()
    if not cleaned:
        return None
    if cleaned not in platega.METHODS:
        log.warning("незнакомый способ оплаты %r — заказ пойдёт способом по умолчанию", cleaned)
        return None
    return cleaned


def _reusable_order(
    db: OrmSession,
    plan: Plan,
    provider: str,
    origin: str,
    user_id: int | None = None,
    email: str | None = None,
    quantity: int = 1,
    payment_method: str | None = None,
) -> Order | None:
    query = (
        select(Order)
        .where(
            Order.status == OrderStatus.PENDING.value,
            Order.provider == provider,
            Order.plan_code == plan.code,
            Order.origin == origin,
            Order.payment_method.is_(None)
            if payment_method is None
            else Order.payment_method == payment_method,
            Order.amount_kopecks == plan.price_kopecks * quantity,
            Order.quantity == quantity,
            Order.currency == plan.currency,
            Order.redirect_url.is_not(None),
        )
        .order_by(Order.created_at.desc())
    )
    if user_id is not None:
        query = query.where(Order.user_id == user_id)
    elif email:
        query = query.where(Order.email == email, Order.user_id.is_(None))
    else:
        return None

    now = utcnow()
    for order in db.scalars(query.limit(3)):
        if order.link_expires_at is not None:
            if order.link_expires_at > now + dt.timedelta(minutes=LINK_SAFETY_MINUTES):
                return order
        elif order.created_at > now - dt.timedelta(minutes=LINK_FRESH_MINUTES):
            return order
    return None


def public_plans(db: OrmSession) -> list[Plan]:
    return [plan for plan in site_plans(db) if plan.price_kopecks > 0]


def site_plans(db: OrmSession) -> list[Plan]:
    return list(
        db.scalars(
            select(Plan)
            .where(Plan.is_active.is_(True), Plan.is_public.is_(True))
            .order_by(Plan.sort_order, Plan.id)
        )
    )


def platform_from_user_agent(user_agent: str | None) -> str | None:
    agent = (user_agent or "").lower()
    if any(mark in agent for mark in ("iphone", "ipod")):
        return "ios"
    if "ipad" in agent:
        return "ios"
    return None


MAX_QUANTITY = 90


def _clamp_quantity(plan: Plan, quantity: int) -> int:
    if plan.period_days > 1:
        return 1
    value = int(quantity or 1)
    if value < 1:
        raise OrderError("укажите, на сколько дней покупаете")
    if value > MAX_QUANTITY:
        raise OrderError(f"за раз можно купить не больше {MAX_QUANTITY} дней")
    return value


def create_order(
    db: OrmSession,
    plan_code: str,
    email: str,
    telegram_id: int | None = None,
    ip: str | None = None,
    provider_name: str | None = None,
    platform: str | None = None,
    quantity: int = 1,
    payment_method: str | None = None,
) -> Order:
    address = normalize_email(email)
    if not address or "@" not in address:
        raise OrderError("нужен настоящий адрес почты")

    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None or not plan.is_active:
        raise OrderError("такого тарифа нет")
    if plan.price_kopecks <= 0:
        raise OrderError("этот тариф не продаётся через сайт")

    count = _clamp_quantity(plan, quantity)
    name = provider_name or payments.active_name()
    method = normalize_payment_method(payment_method)
    existing = _reusable_order(
        db, plan, name, origin="site", email=address, quantity=count, payment_method=method
    )
    if existing is not None:
        return existing

    order = Order(
        plan_code=plan.code,
        email=address,
        telegram_id=telegram_id,
        quantity=count,
        amount_kopecks=plan.price_kopecks * count,
        currency=plan.currency,
        status=OrderStatus.PENDING.value,
        provider=name,
        payment_method=method,
        ip=None,
        platform=(platform or "").strip().lower() or None,
        is_renewal=users.find_by_email(db, address) is not None,
    )
    return _register_with_provider(db, order, name)


def create_order_for_user(
    db: OrmSession,
    user: User,
    plan_code: str,
    origin: str = "site",
    ip: str | None = None,
    provider_name: str | None = None,
    platform: str | None = None,
    quantity: int = 1,
    payment_method: str | None = None,
) -> Order:
    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None or not plan.is_active:
        raise OrderError("такого тарифа нет")
    if plan.price_kopecks <= 0:
        raise OrderError("этот тариф не продаётся")

    count = _clamp_quantity(plan, quantity)
    name = provider_name or payments.active_name()
    method = normalize_payment_method(payment_method)
    existing = _reusable_order(
        db, plan, name, origin=origin, user_id=user.id, quantity=count, payment_method=method
    )
    if existing is not None:
        return existing

    order = Order(
        plan_code=plan.code,
        email=user.email_plain or "",
        telegram_id=user.telegram_id,
        quantity=count,
        amount_kopecks=plan.price_kopecks * count,
        currency=plan.currency,
        status=OrderStatus.PENDING.value,
        provider=name,
        payment_method=method,
        ip=None,
        platform=(platform or "").strip().lower() or None,
        origin=origin,
        user_id=user.id,
        is_renewal=True,
    )
    return _register_with_provider(db, order, name)


def _register_with_provider(db: OrmSession, order: Order, name: str) -> Order:
    db.add(order)
    db.commit()
    db.refresh(order)

    try:
        provider = payments.get(name)
        session = provider.create_payment(order)
    except (payments.PaymentError, payments.UnknownProvider) as exc:
        order.status = OrderStatus.FAILED.value
        order.failure_reason = str(exc)
        db.commit()
        detail = getattr(exc, "body", "") or ""
        if order.payment_method and "paymentMethod" in detail:
            raise OrderError(
                "этот способ оплаты сейчас недоступен — выберите другой"
            ) from exc
        raise OrderError(str(exc)) from exc

    order.provider_payment_id = session.payment_id
    order.redirect_url = session.redirect_url
    order.link_expires_at = session.expires_at
    db.commit()
    db.refresh(order)

    if name == payments.MockProvider.name:
        log.info("заказ %s создан в режиме имитации оплаты", order.id)

    return order


def record_paid_order(
    db: OrmSession,
    user: User,
    plan: Plan,
    *,
    provider: str,
    payment_method: str | None,
    external_id: str,
    amount_kopecks: int,
    quantity: int = 1,
    subscription_id: int | None = None,
    origin: str = "bot",
) -> Order | None:
    order = Order(
        plan_code=plan.code,
        email=user.email_plain or "",
        telegram_id=user.telegram_id,
        quantity=quantity,
        amount_kopecks=amount_kopecks,
        currency=plan.currency,
        status=OrderStatus.PAID.value,
        provider=provider,
        payment_method=payment_method,
        provider_payment_id=external_id,
        ip=None,
        origin=origin,
        user_id=user.id,
        subscription_id=subscription_id,
        is_renewal=True,
        paid_at=utcnow(),
    )
    db.add(order)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        log.warning("заказ по платежу %s/%s уже есть — повтор пропускаем", provider, external_id)
        return None

    db.refresh(order)
    return order


def find(db: OrmSession, order_id: str) -> Order | None:
    return db.get(Order, order_id)


def expire_stale(db: OrmSession) -> int:
    deadline = utcnow() - dt.timedelta(hours=settings().order_ttl_hours)
    stale = list(
        db.scalars(
            select(Order).where(
                Order.status == OrderStatus.PENDING.value, Order.created_at < deadline
            )
        )
    )
    for order in stale:
        order.status = OrderStatus.EXPIRED.value
    if stale:
        db.commit()
        log.info("просрочено заказов: %d", len(stale))
    return len(stale)


class Fulfilment:

    __slots__ = ("order", "user", "password", "is_renewal", "expires_at")

    def __init__(
        self,
        order: Order,
        user: User,
        password: str | None,
        is_renewal: bool,
        expires_at: dt.datetime,
    ) -> None:
        self.order = order
        self.user = user
        self.password = password
        self.is_renewal = is_renewal
        self.expires_at = expires_at


def fulfil(db: OrmSession, order: Order, manual_by: int | None = None) -> Fulfilment:
    done = _already_fulfilled(db, order)
    if done is not None:
        return done

    plan = db.scalar(select(Plan).where(Plan.code == order.plan_code))
    if plan is None:
        raise PanelError(f"тариф «{order.plan_code}» удалён, выдать нечего")

    existing = db.get(User, order.user_id) if order.user_id else None
    if existing is None and order.email:
        existing = users.find_by_email(db, order.email)
    password: str | None = None

    if existing is not None:
        user = existing
        is_renewal = True
        if user.is_blocked:
            user.is_blocked = False
            user.blocked_reason = None
            user.blocked_at = None
        user.is_active = True
    else:
        is_renewal = False
        password = credentials.gen_password()
        user = User(
            login=credentials.free_login(db),
            password_hash=hash_password(password),
            password_enc=crypto.encrypt_or_none(password),
            telegram_id=order.telegram_id,
        )
        user.set_email(order.email)
        db.add(user)
        db.flush()

    if order.telegram_id and not user.telegram_id:
        user.telegram_id = order.telegram_id

    if order.platform == "ios":
        user.ios_access = True

    subscription = grant_subscription(
        db,
        user,
        days=plan.period_days * max(1, order.quantity or 1),
        plan=plan,
        price=float(Decimal(order.amount_kopecks) / 100),
        commit=False,
    )

    order.status = OrderStatus.PAID.value
    order.paid_at = order.paid_at or utcnow()
    order.user_id = user.id
    order.subscription_id = subscription.id
    order.is_renewal = is_renewal
    order.failure_reason = None

    _register_payment(db, order, user, subscription.id)
    _enqueue_delivery(db, order, user, is_renewal)

    if manual_by is not None:
        db.add(
            AuditLog(
                admin_id=manual_by,
                action="order.fulfil_manual",
                target=order.id,
                detail=f"{order.email}, {order.amount_kopecks / 100:.2f} {order.currency}",
            )
        )
    db.add(
        AuditLog(
            admin_id=manual_by,
            action="user.create" if not is_renewal else "user.renew",
            target=user.public_id,
            detail=f"заказ {order.id[:8]}, тариф {plan.code}",
        )
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fresh = db.get(Order, order.id, populate_existing=True)
        done = _already_fulfilled(db, fresh) if fresh is not None else None
        if done is None:
            raise
        log.warning("заказ %s выдан параллельной попыткой, эта отменена", order.id)
        return done

    db.refresh(user)

    user.traffic_used_bytes = 0
    user.traffic_reset_at = utcnow()
    db.commit()

    _ensure_keys_safely(db, user)

    from .referrals import credit_purchase

    credit_purchase(db, user)

    return Fulfilment(order, user, password, is_renewal, subscription.expires_at)


def _already_fulfilled(db: OrmSession, order: Order) -> Fulfilment | None:
    if order.status != OrderStatus.PAID.value or not order.user_id:
        return None
    user = db.get(User, order.user_id)
    sub = user.active_subscription() if user else None
    return Fulfilment(order, user, None, True, sub.expires_at if sub else utcnow())


def _register_payment(db: OrmSession, order: Order, user: User, subscription_id: int) -> None:
    from ..models import Payment

    db.add(
        Payment(
            user_id=user.id,
            subscription_id=subscription_id,
            order_id=order.id,
            amount=Decimal(order.amount_kopecks) / 100,
            currency=order.currency,
            method=f"{order.provider} · {order.payment_method}"
            if order.payment_method
            else order.provider,
            external_id=order.provider_payment_id,
            comment=f"Заказ {order.id[:8]}, тариф {order.plan_code}",
            paid_at=order.paid_at or utcnow(),
        )
    )


def _enqueue_delivery(db: OrmSession, order: Order, user: User, is_renewal: bool) -> None:
    from ..models import DeliveryJob

    template = "renewed" if is_renewal else "credentials"
    email = order.email or user.email_plain
    if email:
        db.add(
            DeliveryJob(
                channel="email",
                template=template,
                target=email,
                user_id=user.id,
                order_id=order.id,
            )
        )
        db.add(
            DeliveryJob(
                channel="email",
                template="receipt",
                target=email,
                user_id=user.id,
                order_id=order.id,
            )
        )
    if order.telegram_id:
        db.add(
            DeliveryJob(
                channel="telegram",
                template=template,
                target=str(order.telegram_id),
                user_id=user.id,
                order_id=order.id,
            )
        )


def _ensure_keys_safely(db: OrmSession, user: User) -> None:
    from . import ios
    from .keys import ensure_keys

    try:
        warnings = ensure_keys(db, user)
        if user.ios_access:
            warnings += ios.sync(db, user)
    except Exception:
        log.exception("не удалось выдать ключи пользователю %s", user.public_id)
        return
    for warning in warnings:
        log.warning("выдача ключей %s: %s", user.public_id, warning)


def refund(db: OrmSession, order: Order, reason: str = "возврат платежа") -> None:
    if order.status == OrderStatus.REFUNDED.value:
        return

    order.status = OrderStatus.REFUNDED.value
    order.failure_reason = reason

    unpaid_days = 0
    if order.subscription_id:
        subscription = db.get(Subscription, order.subscription_id)
        if subscription is not None:
            unpaid_days = _shrink_subscription_after_refund(db, order, subscription)

    _register_refund(db, order, reason)

    user = db.get(User, order.user_id) if order.user_id else None
    if user is not None:
        from .referrals import revoke_purchase_bonus

        revoke_purchase_bonus(db, user, reason)

        if unpaid_days > 0:
            from .transfers import claw_back

            claw_back(db, user, unpaid_days, reason, commit=False)
    db.commit()

    if user is not None:
        db.refresh(user)
        _close_access_after_refund(db, order, user, reason)

    db.add(AuditLog(action="order.refund", target=order.id, detail=reason))
    db.commit()


def _shrink_subscription_after_refund(db: OrmSession, order: Order, subscription: Subscription) -> int:
    plan = db.scalar(select(Plan).where(Plan.code == order.plan_code))
    days = (plan.period_days if plan else subscription.period_days) * max(1, order.quantity or 1)
    before = subscription.expires_at
    subscription.expires_at -= dt.timedelta(days=days)
    if subscription.expires_at <= subscription.starts_at:
        subscription.expires_at = subscription.starts_at
        subscription.is_cancelled = True

    cut = (before - subscription.expires_at).days
    return max(0, days - cut)


def _register_refund(db: OrmSession, order: Order, reason: str) -> None:
    from ..models import Payment

    original = db.scalar(
        select(Payment).where(Payment.order_id == order.id, Payment.amount > 0)
    )
    if original is None:
        return
    compensated = db.scalar(
        select(Payment.id).where(Payment.order_id == order.id, Payment.amount < 0)
    )
    if compensated is not None:
        return

    db.add(
        Payment(
            user_id=original.user_id,
            subscription_id=original.subscription_id,
            order_id=order.id,
            amount=-original.amount,
            currency=original.currency,
            method=original.method,
            external_id=original.external_id,
            comment=f"Возврат по заказу {order.id[:8]}: {reason}",
            paid_at=utcnow(),
        )
    )


def _close_access_after_refund(db: OrmSession, order: Order, user: User, reason: str) -> None:
    from .keys import revoke_key
    from .users import revoke_access

    now = utcnow()
    running = any(
        s.starts_at <= now < s.expires_at and not s.is_cancelled for s in user.subscriptions
    )
    remaining = any(not s.is_cancelled and s.expires_at > now for s in user.subscriptions)

    if running:
        return

    if not remaining:
        problems = revoke_access(db, user, reason=reason)
        for problem in problems:
            log.error("возврат по заказу %s: пир не снят — %s", order.id, problem)
        return

    for key in list(user.keys):
        if key.revoked_at is not None:
            continue
        try:
            revoke_key(db, key)
        except Exception as exc:
            log.error("возврат по заказу %s: пир не снят — %s: %s", order.id, key.server.name, exc)
