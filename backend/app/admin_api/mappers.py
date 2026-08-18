"""
Превращение записей базы в ответы API.

Вынесено из маршрутов: одна и та же сборка строки пользователя нужна и в
списке, и в карточке, и после каждого действия — дублировать её негде.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session as OrmSession

from ..services import ios
from ..models import (
    HANDSHAKE_WINDOW,
    IOS_MAX_KEYS,
    AuditLog,
    DeliveryJob,
    Order,
    Server,
    Session,
    TunnelFile,
    User,
    UserKey,
    is_ios_slot,
    utcnow,
)
from . import schemas

# Сессия считается живой, если приложение отмечалось последние 10 минут.
ONLINE_WINDOW = dt.timedelta(minutes=10)


def user_status(user: User, now: dt.datetime | None = None) -> str:
    """
    Один короткий статус вместо четырёх флагов.

    Порядок важен: заблокированный с кончившейся подпиской — всё-таки
    заблокированный, это решение администратора, а не следствие календаря.

    У человека с действующим доступом статус отвечает на вопрос «пользуется
    ли он сервисом прямо сейчас»: `online` — идёт трафик через наш узел,
    `offline` — доступ есть, но туннель не поднят. Прежнее `active`
    отвечало на другой вопрос — оплачено или нет, — и совпадало с зелёной
    точкой у всех подряд, включая тех, кто ни разу не подключался.
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
    return "online" if user.is_vpn_connected(moment) else "offline"


def _is_online(session: Session, now: dt.datetime) -> bool:
    return session.revoked_at is None and session.last_seen_at >= now - ONLINE_WINDOW


def _session_connected(user: User, session: Session, now: dt.datetime) -> bool:
    """
    Идёт ли через это устройство трафик прямо сейчас.

    «Приложение открыто» и «туннель поднят» — разные вещи, и в списке
    устройств администратору нужна вторая: отключать имеет смысл того, кто
    в VPN. Смотрим по рукопожатию пиров этого устройства.
    """
    if session.revoked_at is not None or not session.is_device:
        return False
    device_id = session.device_key
    for key in user.keys:
        if key.revoked_at is not None or (key.device_id or "") != device_id:
            continue
        if key.last_handshake_at is not None and key.last_handshake_at > now - HANDSHAKE_WINDOW:
            return True
    return False


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
        # Расшифровка адреса — почта в базе лежит шифротекстом. Панель —
        # единственное место, где адрес показывается, и это осознанно.
        email=user.email_plain,
        telegram_id=user.telegram_id,
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
        last_login_at=user.last_login_at,
        # Онлайн — это подключённый туннель, а не открытое приложение.
        is_online=user.is_vpn_connected(moment),
        app_online=any(_is_online(s, moment) for s in sessions),
        last_handshake_at=user.last_handshake(),
        sessions_count=sum(1 for s in sessions if s.revoked_at is None),
        # Лимит тарифа считает устройства, а не входы: вкладка кабинета в
        # браузере места в нём не занимает — см. models.WEB_PLATFORMS.
        devices_used=len(user.device_sessions(moment)),
        device_limit=user.device_limit(moment),
        servers_count=sum(1 for k in user.keys if k.revoked_at is None),
        ios_access=user.ios_access,
        ios_blocked=user.ios_blocked,
        # Ключей столько, сколько номеров, а не строк: на каждый номер
        # приходится по пиру на каждой стране, и «ключей 3» у человека с
        # одним ключом и тремя странами — неправда.
        ios_keys_count=len(
            {k.device_id for k in user.keys if k.revoked_at is None and is_ios_slot(k.device_id)}
        ),
        created_at=user.created_at,
    )


def order_row(order: Order, delivery_status: str | None = None) -> schemas.OrderRow:
    return schemas.OrderRow(
        id=order.id,
        plan_code=order.plan_code,
        plan_name=order.plan.name if order.plan else None,
        email=order.email,
        telegram_id=order.telegram_id,
        amount_kopecks=order.amount_kopecks,
        currency=order.currency,
        status=order.status,
        provider=order.provider,
        provider_payment_id=order.provider_payment_id,
        is_renewal=order.is_renewal,
        failure_reason=order.failure_reason,
        user_id=order.user_id,
        user_login=order.user.login if order.user else None,
        created_at=order.created_at,
        paid_at=order.paid_at,
        delivery_status=delivery_status,
    )


def delivery_row(job: DeliveryJob) -> schemas.DeliveryRow:
    return schemas.DeliveryRow(
        id=job.id,
        channel=job.channel,
        template=job.template,
        target=job.target,
        order_id=job.order_id,
        user_id=job.user_id,
        user_login=job.user.login if job.user else None,
        attempts=job.attempts,
        last_error=job.last_error,
        next_attempt_at=job.next_attempt_at,
        sent_at=job.sent_at,
        created_at=job.created_at,
    )


def audit_row(entry: AuditLog, admin_login: str | None = None) -> schemas.AuditRow:
    return schemas.AuditRow(
        id=entry.id,
        admin_id=entry.admin_id,
        admin_login=admin_login,
        action=entry.action,
        target=entry.target,
        detail=entry.detail,
        created_at=entry.created_at,
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
        device_id=key.device_id or "",
        address=key.address,
        public_key=key.public_key,
        rx_bytes=key.rx_bytes,
        tx_bytes=key.tx_bytes,
        last_handshake_at=key.last_handshake_at,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


def user_detail(
    user: User, now: dt.datetime | None = None, orders: list[Order] | None = None
) -> schemas.UserDetail:
    moment = now or utcnow()
    row = user_row(user, moment)

    return schemas.UserDetail(
        **row.model_dump(),
        note=user.note,
        has_password=bool(user.password_enc),
        orders=[order_row(o) for o in (orders or [])],
        blocked_reason=user.blocked_reason,
        blocked_at=user.blocked_at,
        traffic_reset_at=user.traffic_reset_at,
        sessions=[
            schemas.SessionOut(
                id=s.id,
                platform=s.platform,
                app_version=s.app_version,
                ip=s.ip,
                device_id=s.device_id,
                device_name=s.device_name,
                created_at=s.created_at,
                last_seen_at=s.last_seen_at,
                expires_at=s.expires_at,
                revoked_at=s.revoked_at,
                is_online=_is_online(s, moment),
                is_device=s.is_device,
                is_connected=_session_connected(user, s, moment),
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
        ios_keys=[ios_key_out(k) for k in ios.keys(user)],
        ios_max_keys=IOS_MAX_KEYS,
        ios_can_add=user.has_access(moment) and ios.free_slot(user) is not None,
    )


def ios_key_out(key: "ios.IosKey") -> schemas.IosKeyOut:
    return schemas.IosKeyOut(
        id=key.id,
        slot=key.slot,
        name=key.name,
        server_id=key.server_id,
        server_name=key.server_name,
        country=key.country,
        country_code=key.country_code,
        city=key.city,
        address=key.address,
        vpn_url=key.vpn_url,
        traffic_bytes=key.traffic_bytes,
        last_handshake_at=key.last_handshake_at,
        created_at=key.created_at,
        is_active=key.is_active,
    )


def tunnel_file_out(entry: TunnelFile, with_content: bool = False) -> schemas.TunnelFileOut:
    return schemas.TunnelFileOut(
        id=entry.id,
        filename=entry.filename,
        version=entry.version,
        size_bytes=entry.size_bytes,
        sha256=entry.sha256,
        note=entry.note,
        is_active=entry.is_active,
        updated_at=entry.updated_at,
        content=entry.content if with_content else None,
    )


def server_out(db: OrmSession, server: Server) -> schemas.ServerOut:
    from ..services.diagnostics import can_serve

    keys = server.keys
    return schemas.ServerOut(
        health_ok=server.health_ok,
        health_summary=server.health_summary,
        health_checked_at=server.health_checked_at,
        can_serve=can_serve(server),
        facts=schemas.ServerFacts(**server.facts) if server.facts else None,
        id=server.id,
        name=server.name,
        country=server.country,
        # Английские названия отдаём как есть, без подстановки по коду:
        # панель показывает их в форме, и справочное значение в поле ввода
        # выглядело бы как заполненное вручную. Подставляет клиентское API,
        # см. _servers_out.
        country_en=server.country_en,
        city=server.city,
        city_en=server.city_en,
        country_code=server.country_code,
        host=server.host,
        port=server.port,
        alt_ports=server.alt_ports or "",
        is_active=server.is_active,
        provisioning=server.provisioning.value,
        sort_order=server.sort_order,
        has_template=bool(server.awg_template),
        ssh_host=server.ssh_host,
        ssh_port=server.ssh_port,
        ssh_user=server.ssh_user,
        has_ssh_secret=bool(server.ssh_key or server.ssh_password),
        keys_total=len(keys),
        keys_active=sum(1 for k in keys if k.revoked_at is None),
        traffic_synced_at=server.traffic_synced_at,
        traffic_error=server.traffic_error,
        created_at=server.created_at,
    )
