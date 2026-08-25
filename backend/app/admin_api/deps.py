from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin, AuditLog


def current_admin(
    authorization: str | None = Header(default=None),
    db: OrmSession = Depends(get_db),
) -> Admin:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен токен")
    session = services.admin_session_for_token(db, authorization.split(" ", 1)[1].strip())
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен недействителен")
    return session.admin


def audit(
    db: OrmSession, admin: Admin | None, action: str, target: str | None = None, detail: str | None = None
) -> None:
    db.add(
        AuditLog(
            admin_id=admin.id if admin else None,
            action=action,
            target=target,
            detail=detail,
        )
    )
    db.commit()


DbDep = Depends(get_db)
AdminDep = Depends(current_admin)
