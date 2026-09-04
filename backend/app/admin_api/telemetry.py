from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin
from . import schemas
from .deps import current_admin

router = APIRouter(tags=["admin:telemetry"])


@router.get("/telemetry", response_model=schemas.TelemetryOut)
def telemetry(
    days: int = Query(default=7, ge=1, le=90),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> schemas.TelemetryOut:
    """Сводка отчётов о подключениях из приложений за последние `days` дней."""
    return schemas.TelemetryOut.model_validate(services.telemetry.summary(db, days))
