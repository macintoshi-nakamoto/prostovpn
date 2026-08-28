from __future__ import annotations

import logging

import datetime as dt

from sqlalchemy import func, or_, select, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import DeliveryJob, Referral, User, new_referral_code, utcnow
from . import telegram
from .billing import add_bonus_days, take_bonus_days
from .errors import PanelError

log = logging.getLogger("panel.referrals")


class ReferralError(PanelError):
    pass


def _find_user(db: OrmSession, telegram_id: int | None) -> User | None:
    if not telegram_id:
        return None
    return db.scalar(
        select(User).where(User.telegram_id == telegram_id).order_by(User.id).limit(1)
    )


def by_inviter(user: User):
    conditions = [Referral.inviter_user_id == user.id]
    if user.telegram_id:
        conditions.append(Referral.inviter_telegram_id == user.telegram_id)
    return or_(*conditions)


def code_for(db: OrmSession, user: User) -> str:
    if user.referral_code:
        return user.referral_code

    for _ in range(5):
        candidate = new_referral_code()
        user.referral_code = candidate
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            db.refresh(user)
            continue
        return candidate

    raise ReferralError("не удалось завести код приглашения, попробуйте позже")


def inviter_by_code(db: OrmSession, code: str | None) -> User | None:
    cleaned = (code or "").strip().upper()
    if not cleaned or len(cleaned) > 16:
        return None
    return db.scalar(select(User).where(User.referral_code == cleaned))


def register(
    db: OrmSession,
    inviter_telegram_id: int,
    invited_telegram_id: int,
    invited_login: str | None = None,
) -> Referral:
    if inviter_telegram_id == invited_telegram_id:
        raise ReferralError("по своей же ссылке дни не начисляются")

    existing = db.scalar(
        select(Referral).where(Referral.invited_telegram_id == invited_telegram_id)
    )
    if existing is not None:
        if existing.voided_at is not None:
            raise ReferralError("это приглашение уже не действует")
        if existing.inviter_telegram_id == inviter_telegram_id:
            return existing
        raise ReferralError("этого человека уже пригласил другой участник")

    invited_user = _find_user(db, invited_telegram_id)
    if invited_user is None and invited_login:
        invited_user = db.scalar(select(User).where(User.login == invited_login))
    if invited_user is not None and invited_user.payments:
        raise ReferralError("у этого человека уже есть оплаченный аккаунт")

    referral = Referral(
        inviter_telegram_id=inviter_telegram_id,
        inviter_user_id=None,
        invited_telegram_id=invited_telegram_id,
        invited_user_id=invited_user.id if invited_user else None,
    )
    db.add(referral)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        found = db.scalar(
            select(Referral).where(Referral.invited_telegram_id == invited_telegram_id)
        )
        if found is None:
            raise
        return found

    db.refresh(referral)
    _settle_join_bonus(db, referral)
    return referral


def register_from_site(db: OrmSession, code: str | None, invited: User) -> Referral | None:
    inviter = inviter_by_code(db, code)
    if inviter is None or inviter.id == invited.id:
        return None

    existing = db.scalar(
        select(Referral).where(
            or_(
                Referral.invited_user_id == invited.id,
                Referral.invited_telegram_id == invited.telegram_id
                if invited.telegram_id
                else False,
            )
        )
    )
    if existing is not None:
        return None

    if invited.payments:
        return None

    referral = Referral(
        inviter_telegram_id=inviter.telegram_id,
        inviter_user_id=inviter.id,
        invited_telegram_id=None,
        invited_user_id=invited.id,
    )
    db.add(referral)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None

    db.refresh(referral)
    _settle_join_bonus(db, referral)
    return referral


def _claim_bonus(db: OrmSession, referral: Referral, field: str, days: int) -> bool:
    stamp = utcnow()
    days_field = f"{field}_days"
    at_field = f"{field}_at"
    claimed = db.execute(
        sa_update(Referral)
        .where(Referral.id == referral.id, getattr(Referral, at_field).is_(None))
        .values(**{at_field: stamp, days_field: days})
    ).rowcount
    db.commit()
    if claimed:
        db.refresh(referral)
    return bool(claimed)


def _join_bonus_exhausted(db: OrmSession, inviter: User) -> bool:
    limit = settings().referral_join_daily_limit
    if limit <= 0:
        return False

    since = utcnow() - dt.timedelta(days=1)
    granted = db.scalar(
        select(func.count(Referral.id)).where(
            by_inviter(inviter),
            Referral.join_bonus_at.is_not(None),
            Referral.join_bonus_at >= since,
            Referral.voided_at.is_(None),
        )
    )
    return bool(granted and granted >= limit)


def _whom(referral: Referral) -> str:
    if referral.invited_telegram_id:
        return str(referral.invited_telegram_id)
    return f"учётка {referral.invited_user_id}" if referral.invited_user_id else "гость"


def _settle_join_bonus(db: OrmSession, referral: Referral) -> bool:
    if referral.join_bonus_at is not None:
        return False

    inviter = referral.inviter or _find_user(db, referral.inviter_telegram_id)
    if inviter is None:
        return False

    days = settings().referral_join_days
    if days <= 0:
        return False

    if _join_bonus_exhausted(db, inviter):
        log.warning("реферал: суточный потолок переходов у %s", inviter.public_id)
        return False

    if not _claim_bonus(db, referral, "join_bonus", days):
        return False

    add_bonus_days(db, inviter, days, f"приглашён {_whom(referral)}", commit=False)
    referral.inviter_user_id = inviter.id
    _notify(db, referral.inviter_telegram_id, inviter, "referral_join", days)
    db.commit()
    log.info("реферал: %s получил +%d дн. за переход %s", inviter.public_id, days, _whom(referral))
    return True


def attach_user(
    db: OrmSession, telegram_id: int, user: User, username: str | None = None
) -> None:
    if not telegram_id:
        return

    # Юзернейм бот знает из самого сообщения — кладём его рядом с id, чтобы
    # в админке человека было видно по @имени. Пустым не затираем: в Telegram
    # юзернейма может не быть вовсе.
    clean = telegram.clean_username(username)
    if clean and user.telegram_username != clean:
        user.telegram_username = clean
        db.commit()

    if not user.telegram_id:
        user.telegram_id = telegram_id
        db.commit()

    invited = db.scalar(
        select(Referral).where(
            Referral.invited_telegram_id == telegram_id, Referral.voided_at.is_(None)
        )
    )
    if invited is not None and invited.invited_user_id is None:
        stale = user.created_at < invited.created_at or bool(user.payments)
        foreign = bool(user.telegram_id) and user.telegram_id != telegram_id
        if stale or foreign:
            _void(
                db,
                invited,
                "учётка существовала до приглашения" if stale else "учётка привязана к другому Telegram",
            )
            return

        invited.invited_user_id = user.id
        db.commit()

    pending = list(
        db.scalars(
            select(Referral).where(
                Referral.inviter_telegram_id == telegram_id,
                Referral.join_bonus_at.is_(None),
            )
        )
    )
    for referral in pending:
        referral.inviter_user_id = user.id
        _settle_join_bonus(db, referral)


def _void(db: OrmSession, referral: Referral, reason: str) -> None:
    referral.voided_at = utcnow()
    referral.void_reason = reason

    inviter = referral.inviter or _find_user(db, referral.inviter_telegram_id)
    if inviter is not None and referral.join_bonus_days > 0:
        take_bonus_days(db, inviter, referral.join_bonus_days, f"отменено: {reason}", commit=False)
        referral.join_bonus_days = 0

    db.commit()
    log.info("реферал %s аннулирован: %s", referral.id, reason)


def credit_purchase(db: OrmSession, user: User) -> bool:
    try:
        return _credit_purchase(db, user)
    except Exception:
        db.rollback()
        log.exception("бонус за покупку приглашённого %s не начислен", user.public_id)
        return False


def _credit_purchase(db: OrmSession, user: User) -> bool:
    conditions = [Referral.invited_user_id == user.id]
    if user.telegram_id:
        conditions.append(Referral.invited_telegram_id == user.telegram_id)
    referral = db.scalar(
        select(Referral)
        .where(
            or_(*conditions),
            Referral.purchase_bonus_at.is_(None),
            Referral.voided_at.is_(None),
        )
        .order_by(Referral.id)
        .limit(1)
    )
    if referral is None:
        return False

    inviter = referral.inviter or _find_user(db, referral.inviter_telegram_id)
    if inviter is None:
        return False
    if inviter.id == user.id:
        return False

    days = settings().referral_purchase_days
    if days <= 0:
        return False

    if not _claim_bonus(db, referral, "purchase_bonus", days):
        return False

    add_bonus_days(db, inviter, days, f"оплата приглашённого {user.public_id}", commit=False)
    referral.invited_user_id = user.id
    referral.inviter_user_id = inviter.id
    _notify(db, referral.inviter_telegram_id or inviter.telegram_id, inviter, "referral_purchase", days)
    db.commit()
    log.info("реферал: %s получил +%d дн. за покупку %s", inviter.public_id, days, user.public_id)
    return True


def revoke_purchase_bonus(db: OrmSession, user: User, reason: str) -> bool:
    try:
        conditions = [Referral.invited_user_id == user.id]
        if user.telegram_id:
            conditions.append(Referral.invited_telegram_id == user.telegram_id)
        referral = db.scalar(
            select(Referral)
            .where(or_(*conditions), Referral.purchase_bonus_at.is_not(None))
            .order_by(Referral.id.desc())
            .limit(1)
        )
        if referral is None or referral.purchase_bonus_days <= 0:
            return False

        inviter = referral.inviter or _find_user(db, referral.inviter_telegram_id)
        if inviter is None:
            return False

        take_bonus_days(
            db,
            inviter,
            referral.purchase_bonus_days,
            f"возврат по учётке {user.public_id}: {reason}",
            commit=False,
        )
        referral.purchase_bonus_days = 0
        log.info("реферал: у %s снят бонус за возврат %s", inviter.public_id, user.public_id)
        return True
    except Exception:
        log.exception("не удалось снять реферальный бонус за возврат %s", user.public_id)
        return False


def stats(db: OrmSession, telegram_id: int) -> dict[str, int]:
    inviter = _find_user(db, telegram_id)
    where = by_inviter(inviter) if inviter else (Referral.inviter_telegram_id == telegram_id)
    rows = list(db.scalars(select(Referral).where(where, Referral.voided_at.is_(None))))
    return {
        "invited": len(rows),
        "purchased": sum(1 for row in rows if row.purchase_bonus_at is not None),
        "days": sum(row.join_bonus_days + row.purchase_bonus_days for row in rows),
        "pending": sum(1 for row in rows if row.join_bonus_at is None),
    }


def for_account(db: OrmSession, user: User) -> dict[str, object]:
    config = settings()
    rows = list(
        db.scalars(
            select(Referral)
            .where(by_inviter(user), Referral.voided_at.is_(None))
            .order_by(Referral.created_at.desc())
        )
    )

    friends = [
        {
            "joined_at": row.created_at,
            "days": row.join_bonus_days + row.purchase_bonus_days,
            "paid": row.purchase_bonus_at is not None,
            "pending": row.join_bonus_at is None,
        }
        for row in rows
    ]

    return {
        "linked": bool(user.telegram_id),
        "telegram_id": user.telegram_id,
        "code": code_for(db, user),
        "days_total": sum(item["days"] for item in friends),
        "invited": len(friends),
        "purchased": sum(1 for item in friends if item["paid"]),
        "pending": sum(1 for item in friends if item["pending"]),
        "join_days": config.referral_join_days,
        "purchase_days": config.referral_purchase_days,
        "friends": friends,
    }


def top(db: OrmSession, limit: int = 20) -> list[dict[str, object]]:
    rows = db.execute(
        select(
            Referral.inviter_telegram_id,
            func.count(Referral.id),
            func.sum(Referral.join_bonus_days + Referral.purchase_bonus_days),
        ).group_by(Referral.inviter_telegram_id)
    ).all()
    result = []
    for telegram_id, count, days in rows:
        inviter = _find_user(db, telegram_id)
        result.append(
            {
                "telegram_id": telegram_id,
                "login": inviter.login if inviter else None,
                "invited": count,
                "days": int(days or 0),
            }
        )
    result.sort(key=lambda row: row["invited"], reverse=True)
    return result[:limit]


def _notify(db: OrmSession, telegram_id: int | None, user: User, template: str, days: int) -> None:
    if not telegram_id:
        return

    db.add(
        DeliveryJob(
            channel="telegram",
            template=template,
            target=str(telegram_id),
            user_id=user.id,
            payload=str(days),
        )
    )
