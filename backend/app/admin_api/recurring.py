from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin, Plan, User
from .deps import audit, current_admin

router = APIRouter(prefix="/recurring", tags=["admin:recurring"])


class RecurringState(BaseModel):
    status: str | None = None
    plan_code: str | None = None
    plan_title: str | None = None
    amount_kopecks: int | None = None
    currency: str | None = None
    interval: str | None = None
    next_charge_at: dt.datetime | None = None
    last_charge_error: str | None = None
    redirect_url: str | None = None


def _user_by_login(db: OrmSession, login: str) -> User:
    user = db.scalar(select(User).where(User.login == login))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"учётка «{login}» не найдена")
    return user


def _state(db: OrmSession, user: User, redirect_always: bool = False) -> RecurringState:
    sub = services.recurring.get_live(db, user)
    if sub is None:
        return RecurringState()
    plan = db.scalar(select(Plan).where(Plan.code == sub.plan_code))
    show_redirect = redirect_always or sub.status == "pending"
    return RecurringState(
        status=sub.status,
        plan_code=sub.plan_code,
        plan_title=plan.name if plan else sub.plan_code,
        amount_kopecks=sub.amount_kopecks,
        currency=sub.currency,
        interval=sub.interval,
        next_charge_at=sub.next_charge_at,
        last_charge_error=sub.last_charge_error,
        redirect_url=sub.redirect_url if show_redirect else None,
    )


@router.get("/by-login/{login}", response_model=RecurringState)
def state(
    login: str,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> RecurringState:
    return _state(db, _user_by_login(db, login))


class RecurringCreateIn(BaseModel):
    login: str
    plan_code: str


@router.post("", response_model=RecurringState, status_code=status.HTTP_201_CREATED)
def create(
    body: RecurringCreateIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> RecurringState:
    user = _user_by_login(db, body.login)
    try:
        services.recurring.create(db, user, body.plan_code, origin="bot")
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "recurring.create_bot", user.public_id, body.plan_code)
    return _state(db, user, redirect_always=True)


class RecurringCancelIn(BaseModel):
    login: str


@router.post("/cancel", response_model=RecurringState)
def cancel(
    body: RecurringCancelIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> RecurringState:
    user = _user_by_login(db, body.login)
    sub = services.recurring.get_live(db, user)
    if sub is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "автосписание не подключено")
    try:
        services.recurring.cancel(db, sub)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "recurring.cancel_bot", user.public_id)
    return _state(db, user)
