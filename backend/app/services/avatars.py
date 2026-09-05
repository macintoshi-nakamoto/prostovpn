"""
Аватарка из Telegram для приложения на телефоне.

Кабинет внутри Telegram получает фото из initData, а приложению взять его
неоткуда: оно входит логином и паролем. Спрашиваем у бота —
`getUserProfilePhotos` отдаёт публичные фото профиля любого, кто не закрыл
их в настройках приватности. Закрыл — фото нет, приложение покажет букву,
как и раньше. Ничего сверх того, что человек и так показывает всему
Telegram, здесь не запрашивается.

Кэш на диске на сутки: приложение просит картинку при каждом запуске, а
бот — не место, куда ходить по сто раз за одним и тем же файлом.
Отсутствие фото тоже запоминаем, но короче: люди ставят аватарку и хотят
увидеть её не через сутки.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from ..config import settings
from .telegram import API

log = logging.getLogger("panel.avatars")

# Сколько держим картинку и сколько — память о её отсутствии.
KEEP_SECONDS = 24 * 3600
KEEP_NONE_SECONDS = 4 * 3600

# Меньше этого — мыло на экране с плотностью 3x, больше — лишние байты
# на каждый запуск приложения. Telegram отдаёт размеры по возрастанию.
MIN_SIDE = 320

# Сколько байт готовы принять: фото профиля весит десятки килобайт, всё,
# что заметно больше, — не фото.
MAX_BYTES = 2 * 1024 * 1024

TIMEOUT = 10.0


def _cache_dir() -> Path | None:
    configured = (settings().avatar_cache_dir or "").strip()
    if not configured:
        return None
    path = Path(configured)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("каталог аватарок %s недоступен: %s", path, exc)
        return None
    return path


def _fresh(path: Path, keep: int) -> bool:
    try:
        return time.time() - path.stat().st_mtime < keep
    except OSError:
        return False


def _telegram_get(method: str, **params: object) -> dict:
    """Один вызов Bot API. Вынесен отдельно, чтобы тесты подменяли сеть целиком."""
    token = settings().telegram_bot_token
    response = httpx.get(f"{API}/bot{token}/{method}", params=params, timeout=TIMEOUT)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or "Telegram ответил без ok")
    return body.get("result") or {}


def _telegram_file(file_path: str) -> bytes:
    token = settings().telegram_bot_token
    with httpx.stream("GET", f"{API}/file/bot{token}/{file_path}", timeout=TIMEOUT) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_BYTES:
                raise RuntimeError("файл больше, чем бывает фото профиля")
            chunks.append(chunk)
    return b"".join(chunks)


def _pick(sizes: list[dict]) -> str | None:
    """Самый мелкий размер, который ещё не мылится. Нет такого — самый крупный."""
    usable = [s for s in sizes if isinstance(s, dict) and s.get("file_id")]
    if not usable:
        return None
    for size in usable:
        if int(size.get("width") or 0) >= MIN_SIDE:
            return str(size["file_id"])
    return str(usable[-1]["file_id"])


def _from_telegram(telegram_id: int) -> bytes | None:
    photos = _telegram_get("getUserProfilePhotos", user_id=telegram_id, limit=1)
    stack = (photos.get("photos") or [[]])[0] if photos.get("total_count") else []
    file_id = _pick(list(stack))
    if not file_id:
        return None
    info = _telegram_get("getFile", file_id=file_id)
    file_path = info.get("file_path")
    if not file_path:
        return None
    return _telegram_file(str(file_path))


def fetch(telegram_id: int) -> bytes | None:
    """
    Фото профиля или None, если его нет или Telegram недоступен.

    Ошибки сети и Bot API глотаем намеренно: аватарка — украшение, и
    падать из-за неё входу в приложение нельзя. В журнал пишем, чтобы
    массовые отказы было видно.
    """
    if not settings().telegram_bot_token:
        return None

    folder = _cache_dir()
    picture = folder / f"{telegram_id}.jpg" if folder else None
    absent = folder / f"{telegram_id}.none" if folder else None

    if picture and _fresh(picture, KEEP_SECONDS):
        try:
            return picture.read_bytes()
        except OSError:
            pass
    if absent and _fresh(absent, KEEP_NONE_SECONDS):
        return None

    try:
        data = _from_telegram(telegram_id)
    except Exception as exc:  # noqa: BLE001 — любая причина: у человека просто не будет фото
        log.warning("аватарка %s: %s", telegram_id, exc)
        return None

    if folder:
        try:
            if data:
                picture.write_bytes(data)
                absent.unlink(missing_ok=True)
            else:
                absent.touch()
                picture.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("кэш аватарок: %s", exc)
    return data


def forget(telegram_id: int) -> None:
    """Сброс кэша — на случай, если человек сменил фото и просит обновить."""
    folder = _cache_dir()
    if not folder:
        return
    for name in (f"{telegram_id}.jpg", f"{telegram_id}.none"):
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError:
            pass
