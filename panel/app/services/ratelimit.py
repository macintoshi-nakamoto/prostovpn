"""
Ограничение частоты: вход и создание заказов.

Счётчик в базе, а не в памяти процесса. Три причины, и каждой достаточно:
uvicorn запускают в несколько воркеров, и память у них разная; перезапуск
панели не должен дарить нападающему чистый лист; замок после серии неудач
обязан пережить и то, и другое.

Окно скользящее по-простому — фиксированные интервалы со сбросом счётчика.
Точный скользящий счётчик здесь не нужен: разница между «пять попыток за
пятнадцать минут» и «пять попыток за окно» не имеет значения для того, кто
подбирает пароль, зато вторая версия — это одна строка в таблице вместо
журнала попыток.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session as OrmSession

from ..models import RateLimit, utcnow


@dataclass(slots=True)
class Verdict:
    allowed: bool
    retry_after: int = 0  # секунд до следующей попытки

    def __bool__(self) -> bool:
        return self.allowed


def check(db: OrmSession, key: str) -> Verdict:
    """Заперт ли ключ прямо сейчас — без увеличения счётчика."""
    bucket = db.get(RateLimit, key)
    now = utcnow()
    if bucket is not None and bucket.locked_until and bucket.locked_until > now:
        return Verdict(False, int((bucket.locked_until - now).total_seconds()) + 1)
    return Verdict(True)


def hit(
    db: OrmSession,
    key: str,
    limit: int,
    window_minutes: int,
    lock_minutes: int = 0,
) -> Verdict:
    """
    Отмечает попытку и говорит, можно ли её выполнять.

    `lock_minutes > 0` — после исчерпания лимита ключ запирается на это
    время, даже если окно уже кончилось. Так ведёт себя вход: пять неудач
    подряд стоят пятнадцати минут ожидания.
    """
    now = utcnow()
    bucket = db.get(RateLimit, key)

    if bucket is None:
        db.add(RateLimit(key=key, count=1, window_start=now))
        db.commit()
        return Verdict(True)

    if bucket.locked_until and bucket.locked_until > now:
        return Verdict(False, int((bucket.locked_until - now).total_seconds()) + 1)

    if now - bucket.window_start >= dt.timedelta(minutes=window_minutes):
        bucket.window_start = now
        bucket.count = 0
        bucket.locked_until = None

    bucket.count += 1
    if bucket.count > limit:
        if lock_minutes > 0:
            bucket.locked_until = now + dt.timedelta(minutes=lock_minutes)
            retry_after = lock_minutes * 60
        else:
            retry_after = int(
                (bucket.window_start + dt.timedelta(minutes=window_minutes) - now).total_seconds()
            ) + 1
        db.commit()
        return Verdict(False, retry_after)

    db.commit()
    return Verdict(True)


def clear(db: OrmSession, key: str) -> None:
    """
    Сбрасывает счётчик — вызывается после удачного входа.

    Без этого человек, который трижды промахнулся мимо пароля и на четвёртый
    вошёл, остался бы с одной попыткой в запасе на ближайшие пятнадцать
    минут.
    """
    bucket = db.get(RateLimit, key)
    if bucket is not None:
        db.delete(bucket)
        db.commit()


def sweep(db: OrmSession, older_than_hours: int = 24) -> int:
    """Убирает отработавшие счётчики, чтобы таблица не росла бесконечно."""
    from sqlalchemy import delete

    deadline = utcnow() - dt.timedelta(hours=older_than_hours)
    result = db.execute(
        delete(RateLimit).where(
            RateLimit.window_start < deadline,
            (RateLimit.locked_until.is_(None)) | (RateLimit.locked_until < utcnow()),
        )
    )
    db.commit()
    return result.rowcount or 0
