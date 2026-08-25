from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import TunnelFile, utcnow
from .errors import PanelError

MAX_BYTES = 2 * 1024 * 1024

KNOWN_SUFFIXES = (".json", ".txt", ".conf", ".csv")


def current(db: OrmSession) -> TunnelFile | None:
    return db.scalar(
        select(TunnelFile)
        .where(TunnelFile.is_active.is_(True))
        .order_by(TunnelFile.updated_at.desc(), TunnelFile.id.desc())
    )


def history(db: OrmSession, limit: int = 20) -> list[TunnelFile]:
    return list(
        db.scalars(
            select(TunnelFile).order_by(TunnelFile.updated_at.desc(), TunnelFile.id.desc()).limit(limit)
        )
    )


def save(
    db: OrmSession,
    content: str,
    filename: str | None = None,
    version: str | None = None,
    note: str | None = None,
) -> TunnelFile:
    body = (content or "").replace("\r\n", "\n").strip()
    if not body:
        raise PanelError("файл пустой — загружать нечего")

    raw = body.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise PanelError(f"файл больше {MAX_BYTES // 1024} КБ — это точно список сайтов?")

    name = (filename or "").strip() or "prostovpn-ru-sites.json"
    name = name.replace("\\", "/").rsplit("/", 1)[-1].replace('"', "")[:128]
    if not name.lower().endswith(KNOWN_SUFFIXES):
        name = f"{name}.json"

    now = utcnow()
    entry = TunnelFile(
        filename=name,
        version=(version or "").strip() or now.strftime("%d.%m.%Y %H:%M"),
        content=body,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        note=(note or "").strip() or None,
        is_active=True,
        updated_at=now,
    )
    db.add(entry)

    for old in db.scalars(select(TunnelFile).where(TunnelFile.is_active.is_(True))):
        old.is_active = False

    db.commit()
    db.refresh(entry)
    return entry


def activate(db: OrmSession, entry_id: int) -> TunnelFile:
    entry = db.get(TunnelFile, entry_id)
    if entry is None:
        raise PanelError("такой версии файла нет")
    for old in db.scalars(select(TunnelFile).where(TunnelFile.is_active.is_(True))):
        old.is_active = False
    entry.is_active = True
    entry.updated_at = utcnow()
    db.commit()
    db.refresh(entry)
    return entry


def remove(db: OrmSession, entry_id: int) -> None:
    entry = db.get(TunnelFile, entry_id)
    if entry is None:
        return
    db.delete(entry)
    db.commit()
