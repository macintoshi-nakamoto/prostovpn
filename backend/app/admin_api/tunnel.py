"""
Файл раздельного туннелирования: загрузить, посмотреть, откатить.

Список сайтов, которые ходят мимо VPN, меняется чаще всего остального в
сервисе, и менять его должно быть не сложнее, чем поменять цену тарифа.
Поэтому здесь нет ни выкладки на сервер, ни правки конфигов: панель кладёт
новую версию в базу, а кабинет, бот и сайт с этого момента отдают её.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin
from . import mappers, schemas
from .deps import audit, current_admin

router = APIRouter(prefix="/tunnel-file", tags=["admin:tunnel"])


@router.get("", response_model=list[schemas.TunnelFileOut])
def list_versions(
    db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> list[schemas.TunnelFileOut]:
    """История версий. Содержимое — отдельным запросом, оно длинное."""
    return [mappers.tunnel_file_out(entry) for entry in services.tunnel.history(db)]


@router.get("/{entry_id}", response_model=schemas.TunnelFileOut)
def get_version(
    entry_id: int, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> schemas.TunnelFileOut:
    """Версия целиком — чтобы посмотреть список и поправить его на месте."""
    from ..models import TunnelFile

    entry = db.get(TunnelFile, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "такой версии файла нет")
    return mappers.tunnel_file_out(entry, with_content=True)


@router.post("", response_model=schemas.TunnelFileOut, status_code=status.HTTP_201_CREATED)
def upload(
    body: schemas.TunnelFileIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.TunnelFileOut:
    """Новая версия файла — она же сразу текущая."""
    try:
        entry = services.tunnel.save(
            db,
            content=body.content,
            filename=body.filename,
            version=body.version,
            note=body.note,
        )
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit(db, admin, "tunnel_file.upload", entry.filename, f"{entry.size_bytes} байт")
    return mappers.tunnel_file_out(entry)


@router.post("/{entry_id}/activate", response_model=schemas.TunnelFileOut)
def activate(
    entry_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.TunnelFileOut:
    """Откат: прежняя версия снова становится текущей."""
    try:
        entry = services.tunnel.activate(db, entry_id)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    audit(db, admin, "tunnel_file.activate", entry.filename, entry.version)
    return mappers.tunnel_file_out(entry)


@router.delete("/{entry_id}", response_model=schemas.ActionResult)
def remove(
    entry_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.ActionResult:
    services.tunnel.remove(db, entry_id)
    audit(db, admin, "tunnel_file.delete", str(entry_id))
    return schemas.ActionResult(ok=True)
