from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..db import get_db
from ..models import Admin, AuditLog
from . import mappers, schemas
from .deps import current_admin

router = APIRouter(prefix="/audit", tags=["admin:audit"])


@router.get("", response_model=list[schemas.AuditRow])
def list_audit(
    action: str | None = Query(default=None, description="Точное имя действия"),
    target: str | None = Query(default=None, description="Публичный id или id заказа"),
    limit: int = Query(default=300, ge=1, le=2000),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> list[schemas.AuditRow]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        query = query.where(AuditLog.action == action)
    if target:
        query = query.where(AuditLog.target == target)

    entries = list(db.scalars(query))
    logins = dict(db.execute(select(Admin.id, Admin.login)).all())
    return [mappers.audit_row(entry, logins.get(entry.admin_id)) for entry in entries]


@router.get("/actions", response_model=list[str])
def list_actions(
    db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> list[str]:
    return sorted(db.scalars(select(AuditLog.action).distinct()))
