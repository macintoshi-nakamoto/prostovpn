"""
Версии приложения: что считать новее и что отдать клиенту.

Сравнение версий — не строковое: «2.10.0» строкой меньше «2.9.0», и без
разбора на числа приложение с 2.10 получало бы предложение «обновиться»
до 2.9 при каждом запуске.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import AppRelease
from .errors import PanelError

PLATFORMS = ("windows", "android", "macos", "linux", "ios")

_PART = re.compile(r"\d+")


def parse_version(value: str | None) -> tuple[int, ...]:
    """
    «2.1.4-beta» → (2, 1, 4). Всё, что не число, отбрасывается.

    Пустая или неразборчивая версия даёт (0,) — такое приложение считается
    самым старым и получит предложение обновиться, что и требуется.
    """
    if not value:
        return (0,)
    parts = tuple(int(p) for p in _PART.findall(value)[:4])
    return parts or (0,)


def is_newer(candidate: str, current: str | None) -> bool:
    return parse_version(candidate) > parse_version(current)


def latest_for(db: OrmSession, platform: str) -> AppRelease | None:
    """
    Самая свежая версия для платформы.

    Сортируем в Python, а не в SQL: в базе версия лежит строкой, и ORDER BY
    по ней даст неверный порядок на двузначных числах.
    """
    rows = list(
        db.scalars(
            select(AppRelease).where(
                AppRelease.platform == platform.lower(), AppRelease.is_active.is_(True)
            )
        )
    )
    if not rows:
        return None
    return max(rows, key=lambda r: (parse_version(r.version), r.released_at))


def check(db: OrmSession, platform: str, current_version: str | None) -> dict[str, object]:
    """Ответ приложению: есть ли обновление и где его взять."""
    release = latest_for(db, platform)
    if release is None:
        return {"update_available": False}

    available = is_newer(release.version, current_version)
    return {
        "update_available": available,
        "version": release.version,
        "url": release.url if available else None,
        "changelog": release.changelog,
        "released_at": release.released_at,
        "size_bytes": release.size_bytes,
        "sha256": release.sha256,
        # Обязательность имеет смысл только когда обновляться есть на что.
        "mandatory": bool(release.is_mandatory and available),
    }


def upsert(
    db: OrmSession,
    platform: str,
    version: str,
    url: str,
    changelog: str | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
    is_mandatory: bool = False,
    is_active: bool = True,
) -> AppRelease:
    platform = platform.lower().strip()
    if platform not in PLATFORMS:
        raise PanelError(f"платформа должна быть одной из: {', '.join(PLATFORMS)}")
    if not version.strip():
        raise PanelError("версия не может быть пустой")
    if not url.strip():
        raise PanelError("нужна ссылка на установщик")

    release = db.scalar(
        select(AppRelease).where(
            AppRelease.platform == platform, AppRelease.version == version.strip()
        )
    )
    if release is None:
        release = AppRelease(platform=platform, version=version.strip())
        db.add(release)

    release.url = url.strip()
    release.changelog = changelog
    release.size_bytes = size_bytes
    release.sha256 = sha256
    release.is_mandatory = is_mandatory
    release.is_active = is_active
    db.commit()
    db.refresh(release)
    return release
