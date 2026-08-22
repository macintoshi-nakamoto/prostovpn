"""
Переводы дней глазами администратора.

Раздел нужен ровно для одного разговора: «мне не пришли дни» или «у меня
пропали дни». По списку видно обе стороны, дату и сколько ушло — и сразу
понятно, был перевод или человек его не завершил.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..config import settings
from ..db import get_db
from ..models import Admin, DayTransfer, User
from .deps import audit, current_admin
from .schemas import Schema

# Поля в camelCase, как во всей админке: этот раздел рисует панель. Бот
# ходит сюда же и читает те же имена — см. utils/panel.py.
router = APIRouter(prefix="/transfers", tags=["admin:transfers"])


class TransferRow(Schema):
    id: int
    days: int
    origin: str
    note: str | None = None
    created_at: dt.datetime

    from_id: int
    from_login: str
    from_public_id: str

    to_id: int
    to_login: str
    to_public_id: str


def _row(db: OrmSession, record: DayTransfer) -> TransferRow:
    sender = db.get(User, record.from_user_id)
    recipient = db.get(User, record.to_user_id)
    return TransferRow(
        id=record.id,
        days=record.days,
        origin=record.origin,
        note=record.note,
        created_at=record.created_at,
        from_id=record.from_user_id,
        from_login=sender.login if sender else "—",
        from_public_id=sender.public_id if sender else "—",
        to_id=record.to_user_id,
        to_login=recipient.login if recipient else "—",
        to_public_id=recipient.public_id if recipient else "—",
    )


@router.get("", response_model=list[TransferRow])
def list_transfers(
    user_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> list[TransferRow]:
    """Все переводы или переводы одного человека — обе стороны сразу."""
    if user_id is not None:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "пользователь не найден")
        rows = services.transfers.history(db, user, limit=limit)
    else:
        rows = services.transfers.recent(db, limit=limit)
    return [_row(db, record) for record in rows]


class AdminTransferIn(Schema):
    from_user_id: int
    recipient: str
    days: int
    note: str | None = None
    # Откуда перевод: bot — человек сделал его сам через Telegram, panel —
    # за него это сделала поддержка. В журнале это разные события, и
    # ограничение частоты у них тоже разное.
    origin: str = "panel"


@router.post("", response_model=TransferRow, status_code=status.HTTP_201_CREATED)
def make_transfer(
    body: AdminTransferIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> TransferRow:
    """
    Перевод руками — когда человек просит поддержку сделать это за него.

    Проверки те же, что и у самостоятельного перевода: администратор не
    может ни создать дни из воздуха, ни увести человека в минус.
    """
    sender = db.get(User, body.from_user_id)
    if sender is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "отправитель не найден")

    origin = "bot" if body.origin == "bot" else "panel"
    if origin == "bot":
        # Тот же лимит, что и на сайте: иначе перевод через Telegram
        # оставался бы способом перебирать чужие логины без счётчика.
        verdict = services.ratelimit.hit(
            db,
            f"transfer:{sender.id}",
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
            db, sender, body.recipient, body.days, origin=origin, note=body.note
        )
    except services.transfers.TransferError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # Ручное действие администратора и перевод, который человек сделал сам,
    # в журнале различаются: по первому спрашивают «кто это сделал».
    audit(
        db,
        admin if origin == "panel" else None,
        "days.transfer_manual" if origin == "panel" else "days.transfer_bot",
        sender.public_id,
        f"{body.days} дн. → {body.recipient}",
    )
    return _row(db, record)
