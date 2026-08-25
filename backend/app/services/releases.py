from __future__ import annotations

import hashlib
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import AppRelease
from .errors import PanelError

log = logging.getLogger("panel.releases")

PLATFORMS = ("windows", "android", "macos", "linux", "ios")

_PART = re.compile(r"\d+")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

MAX_INSTALLER_BYTES = 1024 * 1024 * 1024

_FETCH_TIMEOUT_SECONDS = 30
_CHUNK = 1 << 20


def parse_version(value: str | None) -> tuple[int, ...]:
    if not value:
        return (0,)
    parts = tuple(int(p) for p in _PART.findall(value)[:4])
    return parts or (0,)


def is_newer(candidate: str, current: str | None) -> bool:
    return parse_version(candidate) > parse_version(current)


def latest_for(db: OrmSession, platform: str) -> AppRelease | None:
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
        "mandatory": bool(release.is_mandatory and available),
    }


def local_installer(url: str) -> Path | None:
    configured = settings().downloads_dir.strip()
    if not configured:
        return None
    root = Path(configured)
    if not root.is_dir():
        return None

    name = Path(unquote(urlparse(url).path)).name
    if not name:
        return None
    root = root.resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def measure(url: str) -> tuple[str, int]:
    local = local_installer(url)
    if local is not None:
        digest = hashlib.sha256()
        size = 0
        with local.open("rb") as stream:
            while chunk := stream.read(_CHUNK):
                digest.update(chunk)
                size += len(chunk)
        if size == 0:
            raise PanelError(f"файл {local.name} пустой")
        return digest.hexdigest(), size
    return _measure_over_network(url)


def _measure_over_network(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise PanelError("ссылка на установщик должна начинаться с http:// или https://")

    digest = hashlib.sha256()
    size = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "prosto-panel"})
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            while chunk := response.read(_CHUNK):
                digest.update(chunk)
                size += len(chunk)
                if size > MAX_INSTALLER_BYTES:
                    raise PanelError("по ссылке больше гигабайта — это точно установщик?")
    except PanelError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PanelError(
            "не удалось скачать установщик по ссылке, чтобы посчитать контрольную сумму. "
            "Положите файл в каталог установщиков панели или впишите sha256 вручную"
        ) from exc

    if size == 0:
        raise PanelError("по ссылке пусто — проверьте адрес установщика")
    return digest.hexdigest(), size


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

    checksum = (sha256 or "").strip().lower()
    if checksum and not _HEX64.match(checksum):
        raise PanelError("sha256 — это ровно 64 шестнадцатеричных знака")

    if is_active and not checksum:
        checksum, measured = measure(url.strip())
        if not size_bytes:
            size_bytes = measured

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
    release.sha256 = checksum or None
    release.is_mandatory = is_mandatory
    release.is_active = is_active
    db.commit()
    db.refresh(release)
    return release
