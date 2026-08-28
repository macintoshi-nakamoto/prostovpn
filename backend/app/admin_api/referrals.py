from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..config import settings
from ..db import get_db
from ..models import Admin, User
from .deps import audit, current_admin

router = APIRouter(prefix="/referrals", tags=["admin:referrals"])


class ReferralStats(BaseModel):

    invited: int = 0
    purchased: int = 0
    days: int = 0
    pending: int = 0
    join_days: int
    purchase_days: int


def _stats(db: OrmSession, telegram_id: int) -> ReferralStats:
    config = settings()
    return ReferralStats(
        **services.referrals.stats(db, telegram_id),
        join_days=config.referral_join_days,
        purchase_days=config.referral_purchase_days,
    )


class InviteIn(BaseModel):
    inviter_telegram_id: int
    invited_telegram_id: int
    invited_login: str | None = None


@router.post("/invite", response_model=ReferralStats, status_code=status.HTTP_201_CREATED)
def invite(
    body: InviteIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> ReferralStats:
    try:
        services.referrals.register(
            db,
            inviter_telegram_id=body.inviter_telegram_id,
            invited_telegram_id=body.invited_telegram_id,
            invited_login=body.invited_login,
        )
    except services.referrals.ReferralError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return _stats(db, body.inviter_telegram_id)


class LinkIn(BaseModel):
    telegram_id: int
    login: str
    # Бот присылает @юзернейм отправителя, если тот у него есть: в админке
    # по нему человека находят, а по одному telegram_id — нет.
    telegram_username: str | None = None


@router.post("/link", response_model=ReferralStats)
def link(
    body: LinkIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> ReferralStats:
    user = db.scalar(select(User).where(User.login == body.login))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"учётка «{body.login}» не найдена")

    services.referrals.attach_user(db, body.telegram_id, user, body.telegram_username)
    return _stats(db, body.telegram_id)


@router.get("/stats/{telegram_id}", response_model=ReferralStats)
def stats(
    telegram_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> ReferralStats:
    return _stats(db, telegram_id)


class TopRow(BaseModel):
    telegram_id: int
    login: str | None = None
    invited: int
    days: int


@router.get("/top", response_model=list[TopRow])
def top(
    limit: int = Query(default=20, ge=1, le=100),
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> list[TopRow]:
    return [TopRow(**row) for row in services.referrals.top(db, limit)]


class BonusIn(BaseModel):
    days: int
    reason: str = "подарок администратора"


@router.post("/bonus/{user_id}")
def bonus(
    user_id: int,
    body: BonusIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> dict[str, object]:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "пользователь не найден")
    try:
        ends_at = services.add_bonus_days(db, user, body.days, body.reason)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit(db, admin, "user.bonus", user.public_id, f"+{body.days} дн., {body.reason}")
    return {"ok": True, "expiresAt": ends_at}
