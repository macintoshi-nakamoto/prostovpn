from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession, selectinload

from .. import services
from ..config import settings
from ..db import get_db
from ..models import Admin, BillingEvent, DeliveryJob, Order, OrderStatus, User
from . import mappers, schemas
from .deps import audit, current_admin

router = APIRouter(prefix="/orders", tags=["admin:orders"])


def _delivery_status(db: OrmSession, order_ids: list[str]) -> dict[str, str]:
    if not order_ids:
        return {}
    rows = db.execute(
        select(DeliveryJob.order_id, DeliveryJob.sent_at, DeliveryJob.attempts).where(
            DeliveryJob.order_id.in_(order_ids)
        )
    ).all()

    status_by_order: dict[str, str] = {}
    for order_id, sent_at, attempts in rows:
        if sent_at is not None:
            state = "sent"
        elif attempts >= settings().delivery_max_attempts:
            state = "failed"
        else:
            state = "pending"
        current = status_by_order.get(order_id)
        if current is None or _severity(state) > _severity(current):
            status_by_order[order_id] = state
    return status_by_order


def _severity(state: str) -> int:
    return {"sent": 0, "pending": 1, "failed": 2}.get(state, 0)


def _load(db: OrmSession, order_id: str) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.plan), selectinload(Order.user))
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "заказ не найден")
    return order


@router.get("", response_model=schemas.OrderList)
def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, description="Поиск по почте, id заказа и платежа"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> schemas.OrderList:
    query = (
        select(Order)
        .options(selectinload(Order.plan), selectinload(Order.user))
        .order_by(Order.created_at.desc())
    )
    if status_filter and status_filter != "all":
        query = query.where(Order.status == status_filter)
    if q:
        needle = f"%{q.strip().lower()}%"
        query = query.where(
            func.lower(Order.email).like(needle)
            | func.lower(Order.id).like(needle)
            | func.lower(func.coalesce(Order.provider_payment_id, "")).like(needle)
        )

    items = list(db.scalars(query.limit(limit)))
    delivery = _delivery_status(db, [o.id for o in items])

    return schemas.OrderList(
        items=[mappers.order_row(order, delivery.get(order.id)) for order in items],
        stats=_stats(db),
    )


def _stats(db: OrmSession) -> schemas.OrderStats:
    counts = dict(
        db.execute(select(Order.status, func.count()).group_by(Order.status)).all()
    )
    revenue = db.scalar(
        select(func.sum(Order.amount_kopecks)).where(Order.status == OrderStatus.PAID.value)
    )
    undelivered = db.scalar(
        select(func.count())
        .select_from(DeliveryJob)
        .where(
            DeliveryJob.sent_at.is_(None),
            DeliveryJob.attempts >= settings().delivery_max_attempts,
        )
    )
    return schemas.OrderStats(
        pending=counts.get(OrderStatus.PENDING.value, 0),
        paid=counts.get(OrderStatus.PAID.value, 0),
        failed=counts.get(OrderStatus.FAILED.value, 0),
        refunded=counts.get(OrderStatus.REFUNDED.value, 0),
        expired=counts.get(OrderStatus.EXPIRED.value, 0),
        undelivered=undelivered or 0,
        revenue_kopecks=int(revenue or 0),
        currency=settings().currency,
    )


@router.get("/{order_id}", response_model=schemas.OrderRow)
def get_order(
    order_id: str, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> schemas.OrderRow:
    order = _load(db, order_id)
    return mappers.order_row(order, _delivery_status(db, [order.id]).get(order.id))


@router.post("/{order_id}/fulfil", response_model=schemas.OrderRow)
def fulfil_manually(
    order_id: str,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.OrderRow:
    order = _load(db, order_id)
    if order.status == OrderStatus.REFUNDED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "по заказу был возврат")

    try:
        services.fulfil(db, order, manual_by=admin.id)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return mappers.order_row(_load(db, order_id))


@router.get("/by-payment/{provider}/{external_id}", response_model=schemas.OrderRow)
def order_by_payment(
    provider: str,
    external_id: str,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.OrderRow:
    order = db.scalar(
        select(Order).where(
            Order.provider == provider,
            Order.provider_payment_id == external_id,
        )
    )
    if order is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"заказ по платежу {provider}/{external_id} не найден"
        )
    return mappers.order_row(order)


@router.post("/{order_id}/refund", response_model=schemas.OrderRow)
def refund_order(
    order_id: str,
    body: schemas.OrderActionIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.OrderRow:
    order = _load(db, order_id)
    reason = body.reason or "возврат оформлен администратором"
    services.refund(db, order, reason=reason)
    audit(db, admin, "order.refund_manual", order.id, reason)
    return mappers.order_row(_load(db, order_id))


deliveries = APIRouter(prefix="/deliveries", tags=["admin:orders"])


@deliveries.get("", response_model=list[schemas.DeliveryRow])
def list_deliveries(
    only_problems: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=1000),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> list[schemas.DeliveryRow]:
    query = (
        select(DeliveryJob)
        .options(selectinload(DeliveryJob.user))
        .order_by(DeliveryJob.created_at.desc())
        .limit(limit)
    )
    if only_problems:
        query = query.where(DeliveryJob.sent_at.is_(None))
    return [mappers.delivery_row(job) for job in db.scalars(query)]


@deliveries.post("/{job_id}/retry", response_model=schemas.DeliveryRow)
def retry_delivery(
    job_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.DeliveryRow:
    job = db.get(DeliveryJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "задание не найдено")
    services.delivery.retry(db, job)
    audit(db, admin, "delivery.retry", str(job_id), f"{job.channel} → {job.target}")
    db.refresh(job)
    return mappers.delivery_row(job)


events = APIRouter(prefix="/billing-events", tags=["admin:orders"])


@events.get("", response_model=list[schemas.BillingEventRow])
def list_events(
    limit: int = Query(default=200, ge=1, le=1000),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> list[schemas.BillingEventRow]:
    rows = db.scalars(
        select(BillingEvent).order_by(BillingEvent.received_at.desc()).limit(limit)
    )
    return [
        schemas.BillingEventRow(
            event_id=row.event_id,
            provider=row.provider,
            kind=row.kind,
            order_id=row.order_id,
            result=row.result,
            received_at=row.received_at,
        )
        for row in rows
    ]


class BotOrderIn(BaseModel):
    login: str
    plan_code: str
    quantity: int = 1
    payment_method: str | None = None


class BotOrderOut(BaseModel):
    id: str
    status: str
    plan_code: str
    amount_kopecks: int
    currency: str
    redirect_url: str | None = None


@router.post("/for-user", response_model=BotOrderOut, status_code=status.HTTP_201_CREATED)
def create_for_user(
    body: BotOrderIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> BotOrderOut:
    user = db.scalar(select(User).where(User.login == body.login))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"учётка «{body.login}» не найдена")

    try:
        order = services.create_order_for_user(
            db,
            user,
            plan_code=body.plan_code,
            origin="bot",
            quantity=body.quantity,
            payment_method=body.payment_method,
        )
    except services.OrderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit(
        db,
        admin,
        "order.create_bot",
        order.id,
        f"{user.login}, {body.plan_code}, {order.payment_method or 'способ по умолчанию'}",
    )
    return BotOrderOut(
        id=order.id,
        status=order.status,
        plan_code=order.plan_code,
        amount_kopecks=order.amount_kopecks,
        currency=order.currency,
        redirect_url=order.redirect_url,
    )
