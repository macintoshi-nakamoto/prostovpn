from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import SubscriptionFreeze, User, utcnow
from .errors import PanelError

log = logging.getLogger("panel.freeze")

# Сколько раз в календарный месяц можно замораживать подписку.
FREEZES_PER_MONTH = 2


def used_this_month(db: OrmSession, user: User, now: dt.datetime | None = None) -> int:
    moment = now or utcnow()
    month_start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return len(
        list(
            db.scalars(
                select(SubscriptionFreeze.id).where(
                    SubscriptionFreeze.user_id == user.id,
                    SubscriptionFreeze.started_at >= month_start,
                )
            )
        )
    )


def left_this_month(db: OrmSession, user: User, now: dt.datetime | None = None) -> int:
    return max(0, FREEZES_PER_MONTH - used_this_month(db, user, now))


def freeze(db: OrmSession, user: User) -> None:
    now = utcnow()
    if user.is_frozen:
        raise PanelError("подписка уже заморожена", "already_frozen")
    if user.is_blocked or not user.is_active:
        raise PanelError("доступ отключён — заморозка недоступна", "no_access")
    if user.active_subscription(now) is None:
        raise PanelError("замораживать нечего: нет действующей подписки", "no_subscription")
    if left_this_month(db, user, now) <= 0:
        raise PanelError(
            f"заморозка доступна {FREEZES_PER_MONTH} раза в месяц — лимит исчерпан",
            "freeze_limit",
        )

    db.add(SubscriptionFreeze(user_id=user.id, started_at=now))
    user.frozen_at = now
    db.commit()

    # Пиры AmneziaWG снимаем сразу, не дожидаясь фонового обхода. Сами ключи
    # (конфиг, адрес, приватный ключ) не трогаем — issue_key вернёт их как есть.
    # VLESS не гасим: этим занимается приложение на клиенте.
    from .keys import revoke_key

    failed = 0
    for key in user.keys:
        if key.revoked_at is None:
            try:
                revoke_key(db, key)
            except Exception:
                failed += 1  # добьёт enforce_access при следующем обходе
    log.info(
        "подписка %s заморожена%s",
        user.public_id,
        f", узлов не ответило: {failed}" if failed else "",
    )


def unfreeze(db: OrmSession, user: User) -> list[str]:
    now = utcnow()
    started = user.frozen_at
    if started is None:
        raise PanelError("подписка не заморожена", "not_frozen")

    pause = now - started
    for sub in user.subscriptions:
        if sub.is_cancelled or sub.expires_at <= started:
            continue
        sub.expires_at += pause
        if sub.starts_at > started:
            sub.starts_at += pause

    row = db.scalar(
        select(SubscriptionFreeze)
        .where(SubscriptionFreeze.user_id == user.id, SubscriptionFreeze.ended_at.is_(None))
        .order_by(SubscriptionFreeze.started_at.desc())
    )
    if row is not None:
        row.ended_at = now
    user.frozen_at = None
    db.commit()

    from .keys import ensure_keys

    warnings = ensure_keys(db, user)
    log.info(
        "подписка %s разморожена, возвращено %d дн. %d ч.",
        user.public_id,
        pause.days,
        pause.seconds // 3600,
    )
    return warnings
