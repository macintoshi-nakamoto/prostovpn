"""Версии приложения: что раздаём клиентам как обновление."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin, AppRelease
from ..services.releases import PLATFORMS, parse_version
from . import schemas
from .deps import audit, current_admin

router = APIRouter(prefix="/releases", tags=["admin:releases"])


@router.get("", response_model=list[schemas.ReleaseOut])
def list_releases(
    db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> list[schemas.ReleaseOut]:
    rows = list(db.scalars(select(AppRelease)))
    # Сортируем в Python: версия лежит строкой, и ORDER BY по ней поставил
    # бы 2.9 выше 2.10.
    rows.sort(key=lambda r: (r.platform, parse_version(r.version)), reverse=True)
    return [schemas.ReleaseOut.model_validate(r) for r in rows]


@router.get("/platforms")
def platforms(_: Admin = Depends(current_admin)) -> list[str]:
    return list(PLATFORMS)


@router.post("", response_model=schemas.ReleaseOut, status_code=status.HTTP_201_CREATED)
def create_release(
    body: schemas.ReleaseIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.ReleaseOut:
    try:
        release = services.upsert_release(
            db,
            platform=body.platform,
            version=body.version,
            url=body.url,
            changelog=body.changelog,
            size_bytes=body.size_bytes,
            sha256=body.sha256,
            is_mandatory=body.is_mandatory,
            is_active=body.is_active,
        )
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit(db, admin, "release.publish", f"{release.platform} {release.version}")
    return schemas.ReleaseOut.model_validate(release)


@router.delete("/{release_id}", response_model=schemas.ActionResult)
def delete_release(
    release_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.ActionResult:
    release = db.get(AppRelease, release_id)
    if release is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "версия не найдена")
    label = f"{release.platform} {release.version}"
    db.delete(release)
    db.commit()
    audit(db, admin, "release.delete", label)
    return schemas.ActionResult(ok=True)
