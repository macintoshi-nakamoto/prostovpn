"""Тарифы: цена, срок и включённый трафик."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..db import get_db
from ..models import Admin, Plan
from . import schemas
from .deps import audit, current_admin

router = APIRouter(prefix="/plans", tags=["admin:plans"])


@router.get("", response_model=list[schemas.PlanOut])
def list_plans(
    db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> list[schemas.PlanOut]:
    rows = db.scalars(select(Plan).order_by(Plan.sort_order, Plan.id))
    return [schemas.PlanOut.model_validate(p) for p in rows]


@router.post("", response_model=schemas.PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    body: schemas.PlanIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.PlanOut:
    if db.scalar(select(Plan).where(Plan.code == body.code)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"тариф «{body.code}» уже есть")
    plan = Plan(
        code=body.code,
        name=body.name,
        price=body.price,
        currency=settings().currency,
        period_days=body.period_days,
        traffic_limit_bytes=body.traffic_limit_bytes,
        is_active=body.is_active,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    audit(db, admin, "plan.create", plan.code)
    return schemas.PlanOut.model_validate(plan)


@router.put("/{plan_id}", response_model=schemas.PlanOut)
def update_plan(
    plan_id: int,
    body: schemas.PlanIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.PlanOut:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "тариф не найден")
    plan.code = body.code
    plan.name = body.name
    plan.price = body.price
    plan.period_days = body.period_days
    plan.traffic_limit_bytes = body.traffic_limit_bytes
    plan.is_active = body.is_active
    db.commit()
    db.refresh(plan)
    audit(db, admin, "plan.update", plan.code)
    return schemas.PlanOut.model_validate(plan)


@router.delete("/{plan_id}", response_model=schemas.ActionResult)
def delete_plan(
    plan_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.ActionResult:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "тариф не найден")
    # Подписки ссылаются на тариф с ON DELETE SET NULL, а код тарифа в них
    # продублирован — история покупок переживёт удаление.
    db.delete(plan)
    db.commit()
    audit(db, admin, "plan.delete", plan.code)
    return schemas.ActionResult(ok=True)
