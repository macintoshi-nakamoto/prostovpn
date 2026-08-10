"""
Превращение записей базы в ответы API.

Вынесено из маршрутов: одна и та же сборка строки пользователя нужна и в
списке, и в карточке, и после каждого действия — дублировать её негде.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session as OrmSession

from ..models import Server, Session, User, UserKey, utcnow
from . import schemas

# Сессия считается живой, если приложение отмечалось последние 10 минут.
ONLINE_WINDOW = dt.timedelta(minutes=10)


def user_status(user: User, now: dt.datetime | None = None) -> str:
    """
    Один короткий статус вместо четырёх флагов.

    Порядок важен: заблокированный с кончившейся подпиской — всё-таки
    заблокированный, это решение администратора, а не следствие календаря.
    """
    moment = now or utcnow()
    if user.is_blocked:
        return "blocked"
    if not user.is_active:
        return "paused"
    if user.active_subscription(moment) is None:
        return "expired"
    if user.traffic_exhausted(moment):
        return "traffic"
    return "active"


def _is_online(session: Session, now: dt.datetime) -> bool:
    return session.revoked_at is None and session.last_seen_at >= now - ONLINE_WINDOW


def user_row(user: User, now: dt.datetime | None = None) -> schemas.UserRow:
    moment = now or utcnow()
    sub = user.active_subscription(moment)
    plan_ref = sub.plan_ref if sub else None

    limit = user.effective_traffic_limit(moment)
    used = user.traffic_used_bytes
    payments = user.payments
    sessions = user.sessions
    last_session = max(sessions, key=lambda s: s.last_seen_at, default=None)
    last_payment = max(payments, key=lambda p: p.paid_at, default=None)

    return schemas.UserRow(
        id=user.id,
        public_id=user.public_id,
        login=user.login,
        name=user.name,
        contact=user.contact,
        status=user_status(user, moment),
        is_active=user.is_active,
        is_blocked=user.is_blocked,
        plan=sub.plan if sub else None,
        plan_name=plan_ref.name if plan_ref else (sub.plan if sub else None),
        price=Decimal(str(sub.price)) if sub else Decimal(0),
        currency=sub.currency if sub else "RUB",
        period_days=sub.period_days if sub else None,
        subscription_started_at=sub.starts_at if sub else None,
        expires_at=sub.expires_at if sub else None,
        days_left=max(0, (sub.expires_at - moment).days) if sub else None,
        traffic_used_bytes=used,
        traffic_limit_bytes=limit,
        traffic_pct=(round(used / limit * 100, 1) if limit else None),
        paid_total=sum((Decimal(str(p.amount)) for p in payments), Decimal(0)),
        last_payment_at=last_payment.paid_at if last_payment else None,
        last_seen_at=last_session.last_seen_at if last_session else None,
        is_online=any(_is_online(s, moment) for s in sessions),
        sessions_count=sum(1 for s in sessions if s.revoked_at is None),
        servers_count=sum(1 for k in user.keys if k.revoked_at is None),
        created_at=user.created_at,
    )


def key_out(key: UserKey) -> schemas.UserKeyOut:
    server = key.server
    return schemas.UserKeyOut(
        id=key.id,
        server_id=server.id,
        server_name=server.name,
        country=server.country,
        country_code=server.country_code,
        city=server.city,
        provisioning=server.provisioning.value,
        address=key.address,
        public_key=key.public_key,
        rx_bytes=key.rx_bytes,
        tx_bytes=key.tx_bytes,
        last_handshake_at=key.last_handshake_at,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


def user_detail(user: User, now: dt.datetime | None = None) -> schemas.UserDetail:
    moment = now or utcnow()
    row = user_row(user, moment)

    return schemas.UserDetail(
        **row.model_dump(),
        note=user.note,
        password_hint=user.password_hint,
        blocked_reason=user.blocked_reason,
        blocked_at=user.blocked_at,
        traffic_reset_at=user.traffic_reset_at,
        sessions=[
            schemas.SessionOut(
                id=s.id,
                platform=s.platform,
                app_version=s.app_version,
                ip=s.ip,
                created_at=s.created_at,
                last_seen_at=s.last_seen_at,
                expires_at=s.expires_at,
                revoked_at=s.revoked_at,
                is_online=_is_online(s, moment),
            )
            for s in sorted(user.sessions, key=lambda s: s.last_seen_at, reverse=True)
        ],
        payments=[
            schemas.PaymentOut(
                id=p.id,
                amount=Decimal(str(p.amount)),
                currency=p.currency,
                method=p.method,
                comment=p.comment,
                paid_at=p.paid_at,
            )
            for p in sorted(user.payments, key=lambda p: p.paid_at, reverse=True)
        ],
        subscriptions=[
            schemas.SubscriptionOut(
                id=s.id,
                plan=s.plan,
                price=Decimal(str(s.price)),
                currency=s.currency,
                period_days=s.period_days,
                auto_renew=s.auto_renew,
                starts_at=s.starts_at,
                expires_at=s.expires_at,
                is_cancelled=s.is_cancelled,
            )
            for s in sorted(user.subscriptions, key=lambda s: s.expires_at, reverse=True)
        ],
        keys=[key_out(k) for k in sorted(user.keys, key=lambda k: k.server_id)],
    )


def server_out(db: OrmSession, server: Server) -> schemas.ServerOut:
    keys = server.keys
    return schemas.ServerOut(
        id=server.id,
        name=server.name,
        country=server.country,
        country_en=server.country_en,
        city=server.city,
        country_code=server.country_code,
        host=server.host,
        port=server.port,
        is_active=server.is_active,
        provisioning=server.provisioning.value,
        sort_order=server.sort_order,
        has_template=bool(server.awg_template),
        keys_total=len(keys),
        keys_active=sum(1 for k in keys if k.revoked_at is None),
        traffic_synced_at=server.traffic_synced_at,
        traffic_error=server.traffic_error,
        created_at=server.created_at,
    )
