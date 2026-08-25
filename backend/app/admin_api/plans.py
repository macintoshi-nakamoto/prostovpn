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
    plan = Plan(code=body.code, currency=settings().currency)
    _apply(plan, body)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    audit(db, admin, "plan.create", plan.code, f"{plan.price_kopecks / 100:.2f}")
    return schemas.PlanOut.model_validate(plan)


def _apply(plan: Plan, body: schemas.PlanIn) -> None:
    plan.name = body.name
    plan.set_price(int(round(float(body.price) * 100)))
    plan.period_days = body.period_days
    plan.traffic_limit_bytes = body.traffic_limit_bytes
    plan.server_limit = body.server_limit
    plan.device_limit = body.device_limit
    plan.allowed_regions = body.allowed_regions or None
    plan.tagline = body.tagline
    plan.is_active = body.is_active
    plan.is_public = body.is_public


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
    _apply(plan, body)
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
    db.delete(plan)
    db.commit()
    audit(db, admin, "plan.delete", plan.code)
    return schemas.ActionResult(ok=True)
