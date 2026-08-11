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

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
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
    now = utcnow()
    locked_until = db.scalar(select(RateLimit.locked_until).where(RateLimit.key == key))
    if locked_until is not None and locked_until > now:
        return Verdict(False, int((locked_until - now).total_seconds()) + 1)
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
    window = dt.timedelta(minutes=window_minutes)

    # Читаем колонкой, а не объектом: сессии живут с expire_on_commit=False
    # (db.py), и загруженный ORM-объект после чужого UPDATE остался бы со
    # старыми значениями.
    row = db.execute(select(RateLimit.locked_until).where(RateLimit.key == key)).first()
    if row is None:
        try:
            db.add(RateLimit(key=key, count=1, window_start=now))
            db.commit()
            return Verdict(True)
        except IntegrityError:
            # Строку в тот же миг завёл соседний воркер. Дальше идём по
            # ветке обновления, иначе эта попытка просто потеряется.
            db.rollback()
    elif row[0] is not None and row[0] > now:
        return Verdict(False, int((row[0] - now).total_seconds()) + 1)

    # Счёт ведёт сама база одним выражением, а не «прочитали в объект,
    # прибавили, записали». Read-modify-write в питоне теряет инкременты:
    # воркеров у uvicorn несколько, параллельные попытки читают одно и то же
    # значение и пишут count+1 поверх друг друга — лимит в пять попыток
    # пропускает десятки. Сброс окна считается тем же выражением: он часть
    # той же гонки, а не отдельное действие.
    stale = RateLimit.window_start < now - window
    db.execute(
        update(RateLimit)
        .where(RateLimit.key == key)
        .values(
            count=case((stale, 1), else_=RateLimit.count + 1),
            window_start=case((stale, now), else_=RateLimit.window_start),
            locked_until=case((stale, None), else_=RateLimit.locked_until),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    row = db.execute(
        select(RateLimit.count, RateLimit.window_start).where(RateLimit.key == key)
    ).first()
    if row is None:
        # Строку унёс sweep между двумя запросами — считаем попытку первой.
        return Verdict(True)
    count, window_start = row

    if count <= limit:
        return Verdict(True)

    if lock_minutes > 0:
        db.execute(
            update(RateLimit)
            .where(RateLimit.key == key)
            .values(locked_until=now + dt.timedelta(minutes=lock_minutes))
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return Verdict(False, lock_minutes * 60)
    return Verdict(False, int((window_start + window - now).total_seconds()) + 1)


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
