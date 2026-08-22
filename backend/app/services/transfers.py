"""
Перевод дней доступа другому человеку.

Дни здесь — не деньги и не бонус: они уже оплачены, просто меняют
владельца. Поэтому перевод ничего не пишет в кассу и не трогает выручку —
он двигает срок у двоих сразу, одной транзакцией.

Главное правило: сумма дней у двоих не меняется. Списание и начисление
происходят в одном коммите, и если начислить не вышло, у отправителя
ничего не пропадает.
"""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as OrmSession

from ..models import AuditLog, DayTransfer, DeliveryJob, User, normalize_email, utcnow
from .billing import add_bonus_days, take_bonus_days
from .errors import PanelError

log = logging.getLogger("panel.transfers")

# Сколько дней можно отдать за раз. Потолок не про жадность, а про
# случайный ноль лишним нажатием: перевести год одним махом можно, а
# «99999» — уже опечатка.
MAX_DAYS = 3650


class TransferError(PanelError):
    """Перевод не состоялся — текст показывается человеку."""


def find_recipient(db: OrmSession, key: str) -> User | None:
    """
    Кому переводим: по логину, публичному идентификатору или почте.

    Три способа, потому что человек называет друга тем, что у него под
    рукой: логин знают по приложению, публичный номер видно в кабинете,
    почту помнят по письму. Регистр не важен ни в одном из них.
    """
    needle = (key or "").strip()
    if not needle:
        return None

    user = db.scalar(select(User).where(User.login == needle))
    if user is not None:
        return user

    upper = needle.upper()
    user = db.scalar(select(User).where(User.public_id == upper))
    if user is not None:
        return user

    address = normalize_email(needle)
    if address and "@" in address:
        from .users import find_by_email

        return find_by_email(db, address)

    # Логин мог быть записан в другом регистре — ищем без учёта регистра.
    return db.scalar(select(User).where(User.login.ilike(needle)))


def transfer(
    db: OrmSession,
    sender: User,
    recipient_key: str,
    days: int,
    origin: str = "site",
    note: str | None = None,
) -> DayTransfer:
    """
    Отдаёт `days` дней другому человеку. Возвращает запись перевода.

    Проверок ровно столько, сколько нужно, чтобы не увести дни в никуда:
    получатель существует и это не сам отправитель, дней больше нуля и они
    у отправителя есть. Всё остальное — обычная арифметика срока.
    """
    if days <= 0:
        raise TransferError("укажите, сколько дней передать")
    if days > MAX_DAYS:
        raise TransferError(f"за раз можно передать не больше {MAX_DAYS} дней")

    recipient = find_recipient(db, recipient_key)
    if recipient is None:
        raise TransferError("такого аккаунта нет — проверьте логин или ID")
    if recipient.id == sender.id:
        raise TransferError("нельзя передать дни самому себе")
    if recipient.is_blocked:
        raise TransferError("этот аккаунт заблокирован — дни ему не уйдут")

    now = utcnow()
    left = sender.access_days_left(now) or 0
    if left <= 0:
        raise TransferError("передавать нечего: оплаченных дней не осталось")
    if days > left:
        raise TransferError(f"у вас {left} дн. — больше передать нельзя")

    # Списание и начисление — одним коммитом: иначе на сбое между ними дни
    # исчезли бы у одного, не появившись у другого.
    take_bonus_days(db, sender, days, f"передано {recipient.public_id}", commit=False)
    add_bonus_days(db, recipient, days, f"получено от {sender.public_id}", commit=False)

    record = DayTransfer(
        from_user_id=sender.id,
        to_user_id=recipient.id,
        days=days,
        origin=origin,
        note=(note or "").strip()[:160] or None,
    )
    db.add(record)
    db.add(
        AuditLog(
            action="days.transfer",
            target=sender.public_id,
            detail=f"{days} дн. → {recipient.public_id} ({recipient.login}), из {origin}",
        )
    )
    _notify(db, recipient, sender, days)
    db.commit()
    db.refresh(record)

    log.info(
        "перевод дней: %s → %s, %d дн. (%s)",
        sender.public_id,
        recipient.public_id,
        days,
        origin,
    )
    return record


def history(db: OrmSession, user: User, limit: int = 20) -> list[DayTransfer]:
    """Переводы этого человека — и отданные, и полученные, свежие сверху."""
    return list(
        db.scalars(
            select(DayTransfer)
            .where(or_(DayTransfer.from_user_id == user.id, DayTransfer.to_user_id == user.id))
            .order_by(DayTransfer.created_at.desc())
            .limit(limit)
        )
    )


def recent(db: OrmSession, limit: int = 100) -> list[DayTransfer]:
    """Все переводы — для раздела панели."""
    return list(
        db.scalars(
            select(DayTransfer).order_by(DayTransfer.created_at.desc()).limit(limit)
        )
    )


def _notify(db: OrmSession, recipient: User, sender: User, days: int) -> None:
    """
    Получателю — сообщение о подарке.

    Тем же транзакционным outbox-ом, что и остальная доставка: задание
    ложится в ту же транзакцию, что и сам перевод. Нет ни почты, ни
    Telegram — молчим: перевод от этого не отменяется.
    """
    if recipient.telegram_id:
        db.add(
            DeliveryJob(
                channel="telegram",
                template="days_received",
                target=str(recipient.telegram_id),
                user_id=recipient.id,
                payload=f"{days}:{sender.public_id}",
            )
        )
        return

    address = recipient.email_plain
    if address:
        db.add(
            DeliveryJob(
                channel="email",
                template="days_received",
                target=address,
                user_id=recipient.id,
                payload=f"{days}:{sender.public_id}",
            )
        )
