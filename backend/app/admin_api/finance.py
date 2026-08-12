"""Деньги: календарь прибыли, сводки и платежи."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin, User, utcnow
from . import schemas
from .deps import audit, current_admin

router = APIRouter(tags=["admin:finance"])


@router.get("/calendar", response_model=schemas.CalendarOut)
def calendar(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> schemas.CalendarOut:
    """Месяц целиком: по каждому дню — полученное и ожидаемое."""
    now = utcnow()
    try:
        data = services.calendar_month(db, year or now.year, month or now.month)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return schemas.CalendarOut.model_validate(data)


@router.get("/revenue", response_model=schemas.RevenueSummary)
def revenue(
    db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> schemas.RevenueSummary:
    return schemas.RevenueSummary.model_validate(services.revenue_summary(db))


@router.get("/dashboard", response_model=schemas.Dashboard)
def dashboard(
    db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> schemas.Dashboard:
    totals = services.dashboard_totals(db)
    return schemas.Dashboard(
        **totals,
        daily=[
            schemas.SeriesPoint(label=label, value=value)
            for label, value in services.revenue_series(db, days=30)
        ],
        monthly=[
            schemas.SeriesPoint(label=label, value=value)
            for label, value in services.revenue_by_month(db, months=12)
        ],
    )


@router.post("/payments", response_model=schemas.PaymentOut, status_code=status.HTTP_201_CREATED)
def add_payment(
    body: schemas.PaymentIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.PaymentOut:
    user = db.get(User, body.user_id) if body.user_id else None
    if body.user_id and user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "пользователь не найден")
    try:
        payment = services.add_payment(
            db,
            amount=body.amount,
            user=user,
            method=body.method,
            comment=body.comment,
            paid_at=body.paid_at,
        )
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "payment.add", user.public_id if user else None, str(body.amount))
    return schemas.PaymentOut.model_validate(payment)
