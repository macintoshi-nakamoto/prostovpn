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

ONLINE_WINDOW = dt.timedelta(minutes=10)


def user_status(user: User, now: dt.datetime | None = None) -> str:
    moment = now or utcnow()
    if user.is_blocked:
        return "blocked"
    if not user.is_active:
        return "paused"
    # Заморозка — отдельный статус, а не «отключён»: доступа нет, но дни
    # целы, и в списке это должно читаться с одного взгляда.
    if user.is_frozen:
        return "frozen"
    if user.active_subscription(moment) is None:
        return "expired"
    if user.traffic_exhausted(moment):
        return "traffic"
    return "online" if user.is_vpn_connected(moment) else "offline"


def _is_online(session: Session, now: dt.datetime) -> bool:
    return session.revoked_at is None and session.last_seen_at >= now - ONLINE_WINDOW


def _session_connected(user: User, session: Session, now: dt.datetime) -> bool:
    if session.revoked_at is not None or not session.is_device:
        return False
    # Та же логика, что в кабинете: ключи и учётки устройства по всем
    # протоколам, для старых сборок — общий ключ учётки.
    return user.device_connected(session.device_key, now)


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
        email=user.email_plain,
        telegram_id=user.telegram_id,
        telegram_username=user.telegram_username,
        status=user_status(user, moment),
        is_active=user.is_active,
        is_blocked=user.is_blocked,
        is_free=user.is_free,
        plan=sub.plan if sub else None,
        plan_name=plan_ref.name if plan_ref else (sub.plan if sub else None),
        price=Decimal(str(sub.price)) if sub else Decimal(0),
        currency=sub.currency if sub else "RUB",
        period_days=sub.period_days if sub else None,
        subscription_started_at=sub.starts_at if sub else None,
        # Дата — «если разморозить сейчас»: у замороженного в базе лежит
        # срок, который уже прошёл, и в списке он выглядел бы как долг.
        expires_at=user.access_ends_if_resumed(moment),
        days_left=user.access_days_left_display(moment),
        is_frozen=user.is_frozen,
        frozen_at=user.frozen_at,
        frozen_days=user.frozen_for(moment).days,
        frozen_days_used=user.frozen_days_used,
        freeze_count=user.freeze_count,
        traffic_used_bytes=used,
        traffic_limit_bytes=limit,
        traffic_pct=(round(used / limit * 100, 1) if limit else None),
        paid_total=sum((Decimal(str(p.amount)) for p in payments), Decimal(0)),
        last_payment_at=last_payment.paid_at if last_payment else None,
        last_seen_at=last_session.last_seen_at if last_session else None,
        last_login_at=user.last_login_at,
        is_online=user.is_vpn_connected(moment),
        app_online=any(_is_online(s, moment) for s in sessions),
        last_handshake_at=user.last_handshake(),
        sessions_count=sum(1 for s in sessions if s.revoked_at is None),
        # Та же цифра, что видит человек в кабинете: входы приложения по
        # одному на device_id плюс iPhone с ключами, которыми пользовались.
        devices_used=user.devices_used(moment),
        device_limit=user.device_limit(moment),
        servers_count=sum(1 for k in user.keys if k.revoked_at is None),
        ios_access=user.ios_access,
        ios_blocked=user.ios_blocked,
        ios_keys_count=len(
            {
                k.device_id
                for k in user.keys
                if is_ios_slot(k.device_id)
                and (k.revoked_at is None or k.disconnected_at is not None)
            }
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
        payment_method=order.payment_method,
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
        endpoint_port=key.endpoint_port,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


def cred_out(cred, now: dt.datetime | None = None) -> schemas.EndpointCredOut:
    moment = now or utcnow()
    server = cred.endpoint.server if cred.endpoint is not None else None
    return schemas.EndpointCredOut(
        id=cred.id,
        server_id=cred.server_id,
        server_name=server.name if server is not None else str(cred.server_id),
        country=server.country if server is not None else None,
        country_code=server.country_code if server is not None else None,
        city=server.city if server is not None else None,
        endpoint_handle=cred.endpoint.handle if cred.endpoint is not None else None,
        endpoint_port=cred.endpoint.listen_port if cred.endpoint is not None else None,
        cred_type=cred.cred_type or "vless",
        device_id=cred.device_id or "",
        label=cred.label,
        rx_bytes=cred.rx_bytes or 0,
        tx_bytes=cred.tx_bytes or 0,
        last_seen_at=cred.last_seen_at,
        is_connected=(
            cred.last_seen_at is not None and cred.last_seen_at > moment - HANDSHAKE_WINDOW
        ),
        created_at=cred.created_at,
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
                device_id=s.device_id,
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
                external_id=p.external_id,
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
        ios_keys=[
            ios_key_out(k, moment, user) for k in ios.keys(user, include_disconnected=True)
        ],
        ios_max_keys=IOS_MAX_KEYS,
        ios_can_add=user.has_access(moment) and ios.free_slot(user) is not None,
        # Учётки VLESS/Hysteria2 — по ним видно Happ, Hiddify и запасной ключ
        # AmneziaVPN: раньше админка их не показывала вовсе, и человек на
        # подписке выглядел так, будто VPN не пользуется.
        creds=[
            cred_out(c, moment)
            for c in sorted(
                (c for c in user.endpoint_creds if c.revoked_at is None),
                key=lambda c: (c.device_id or "", c.server_id, c.id),
            )
        ],
    )


def ios_key_out(
    key: "ios.IosKey", now: dt.datetime | None = None, user: User | None = None
) -> schemas.IosKeyOut:
    moment = now or utcnow()
    # Ключ iPhone идёт вместе с запасной учёткой VLESS того же слота — она
    # тоже считается за подключение.
    via_cred = user is not None and user.device_connected(f"ios-{key.slot}", moment)
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
        is_connected=key.is_active
        and (
            (
                key.last_handshake_at is not None
                and key.last_handshake_at > moment - HANDSHAKE_WINDOW
            )
            or via_cred
        ),
        disconnected=key.disconnected,
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
        last_ok_at=server.last_ok_at,
        down_since=server.down_since,
        alert_sent_at=server.alert_sent_at,
        created_at=server.created_at,
    )
