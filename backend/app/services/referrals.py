"""
Приглашения: кто кого привёл и сколько дней за это подарено.

Правило простое: за перешедшего по ссылке — два дня, за его первую
оплату — ещё пять. Считает и начисляет панель, а не бот: дни доступа и
факт оплаты живут здесь, и бот, узнавший о покупке опросом, всегда
опаздывал бы и иногда врал.

Порядок начисления устроен так, чтобы бонус не потерялся и не удвоился:

* приглашение записывается сразу, даже если у пригласившего ещё нет
  учётки в панели, — тогда бонус висит неначисленным и догоняется, как
  только учётка появится (`attach_user`);
* «за переход» и «за покупку» — два независимых начисления с отдельными
  отметками, и каждое проверяет свою отметку перед выдачей;
* уникальность `invited_telegram_id` в базе закрывает накрутку повторными
  переходами по ссылке: второй раз того же человека привести нельзя.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import DeliveryJob, Referral, User, utcnow
from .billing import add_bonus_days
from .errors import PanelError

log = logging.getLogger("panel.referrals")


class ReferralError(PanelError):
    """Приглашение не засчитано — текст показывается человеку в боте."""


def _find_user(db: OrmSession, telegram_id: int | None) -> User | None:
    if not telegram_id:
        return None
    return db.scalar(select(User).where(User.telegram_id == telegram_id).limit(1))


# --- переход по ссылке --------------------------------------------------------


def register(
    db: OrmSession,
    inviter_telegram_id: int,
    invited_telegram_id: int,
    invited_login: str | None = None,
) -> Referral:
    """
    Записывает переход по ссылке и, если можно, дарит дни пригласившему.

    Отказы здесь — часть логики, а не ошибки: по своей ссылке ходят сами,
    чужие ссылки пересылают друг другу, а один и тот же человек переходит
    по разным ссылкам. Все три случая заканчиваются отказом с понятным
    текстом, и ни один не должен ронять бота.
    """
    if inviter_telegram_id == invited_telegram_id:
        raise ReferralError("по своей же ссылке дни не начисляются")

    existing = db.scalar(
        select(Referral).where(Referral.invited_telegram_id == invited_telegram_id)
    )
    if existing is not None:
        if existing.inviter_telegram_id == inviter_telegram_id:
            return existing
        raise ReferralError("этого человека уже пригласил другой участник")

    invited_user = _find_user(db, invited_telegram_id)
    if invited_user is None and invited_login:
        invited_user = db.scalar(select(User).where(User.login == invited_login))
    # Учётка старше приглашения — это не новый клиент, а свой же второй заход
    # через чужую ссылку. Дни за такого не начисляем.
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
        # Гонка: тот же человек нажал ссылку дважды подряд.
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


def _settle_join_bonus(db: OrmSession, referral: Referral) -> bool:
    """Дарит дни за переход, если ещё не дарили и есть кому."""
    if referral.join_bonus_at is not None:
        return False

    inviter = referral.inviter or _find_user(db, referral.inviter_telegram_id)
    if inviter is None:
        # Пригласивший ещё не завёл учётку — бонус подождёт до attach_user.
        return False

    days = settings().referral_join_days
    if days <= 0:
        return False

    add_bonus_days(db, inviter, days, f"приглашён {referral.invited_telegram_id}", commit=False)
    referral.inviter_user_id = inviter.id
    referral.join_bonus_days = days
    referral.join_bonus_at = utcnow()
    _notify(db, referral.inviter_telegram_id, inviter, "referral_join", days)
    db.commit()
    log.info(
        "реферал: %s получил +%d дн. за переход %s",
        inviter.public_id,
        days,
        referral.invited_telegram_id,
    )
    return True


# --- связывание учётки --------------------------------------------------------


def attach_user(db: OrmSession, telegram_id: int, user: User) -> None:
    """
    Связывает Telegram-аккаунт с учёткой панели — в обеих ролях сразу.

    Зовётся, когда бот узнал логин: при входе и при регистрации. Заодно
    догоняет бонус за переход, если пригласивший завёл учётку уже после
    того, как его ссылкой воспользовались.
    """
    if not telegram_id:
        return

    # Телеграм на учётке — то, по чему потом ищут заказы и бонусы.
    if not user.telegram_id:
        user.telegram_id = telegram_id
        db.commit()

    invited = db.scalar(select(Referral).where(Referral.invited_telegram_id == telegram_id))
    if invited is not None and invited.invited_user_id is None:
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


# --- первая оплата приглашённого ---------------------------------------------


def credit_purchase(db: OrmSession, user: User) -> bool:
    """
    Дарит дни за первую оплату приглашённого. Зовётся при выдаче заказа.

    Ошибки внутри гасятся: выдача оплаченного доступа не должна срываться
    из-за подарка. Бонус в этом случае просто не начислится, и это видно в
    журнале — в отличие от неоткрывшегося после оплаты доступа.
    """
    try:
        return _credit_purchase(db, user)
    except Exception:  # pragma: no cover - подарок не ломает выдачу
        db.rollback()
        log.exception("бонус за покупку приглашённого %s не начислен", user.public_id)
        return False


def _credit_purchase(db: OrmSession, user: User) -> bool:
    # Ищем и по учётке, и по Telegram: связь могла не успеть проставиться —
    # человек мог купить раньше, чем вошёл в бота под своим логином.
    conditions = [Referral.invited_user_id == user.id]
    if user.telegram_id:
        conditions.append(Referral.invited_telegram_id == user.telegram_id)
    referral = db.scalar(select(Referral).where(or_(*conditions)))
    if referral is None or referral.purchase_bonus_at is not None:
        return False

    inviter = referral.inviter or _find_user(db, referral.inviter_telegram_id)
    if inviter is None:
        return False
    if inviter.id == user.id:
        return False

    days = settings().referral_purchase_days
    if days <= 0:
        return False

    add_bonus_days(db, inviter, days, f"оплата приглашённого {user.public_id}", commit=False)
    referral.invited_user_id = user.id
    referral.inviter_user_id = inviter.id
    referral.purchase_bonus_days = days
    referral.purchase_bonus_at = utcnow()
    _notify(db, referral.inviter_telegram_id, inviter, "referral_purchase", days)
    db.commit()
    log.info("реферал: %s получил +%d дн. за покупку %s", inviter.public_id, days, user.public_id)
    return True


# --- витрина ------------------------------------------------------------------


def stats(db: OrmSession, telegram_id: int) -> dict[str, int]:
    """Сводка для экрана «Друзья» в боте."""
    rows = list(
        db.scalars(select(Referral).where(Referral.inviter_telegram_id == telegram_id))
    )
    return {
        "invited": len(rows),
        "purchased": sum(1 for row in rows if row.purchase_bonus_at is not None),
        "days": sum(row.join_bonus_days + row.purchase_bonus_days for row in rows),
        "pending": sum(1 for row in rows if row.join_bonus_at is None),
    }


def top(db: OrmSession, limit: int = 20) -> list[dict[str, object]]:
    """Кто сколько привёл — для раздела панели."""
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


# --- уведомление --------------------------------------------------------------


def _notify(db: OrmSession, telegram_id: int, user: User, template: str, days: int) -> None:
    """
    Сообщение в Telegram о подаренных днях.

    Тем же транзакционным outbox-ом, что и остальная доставка: задание
    ложится в ту же транзакцию, что и сам бонус, а отправкой занимается
    обходчик очереди. Без токена бота задание просто не отправится и
    останется в очереди — деньги и дни от этого не страдают.
    """
    db.add(
        DeliveryJob(
            channel="telegram",
            template=template,
            target=str(telegram_id),
            user_id=user.id,
            payload=str(days),
        )
    )
