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
    retry_after: int = 0

    def __bool__(self) -> bool:
        return self.allowed


def check(db: OrmSession, key: str) -> Verdict:
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
    now = utcnow()
    window = dt.timedelta(minutes=window_minutes)

    row = db.execute(select(RateLimit.locked_until).where(RateLimit.key == key)).first()
    if row is None:
        try:
            db.add(RateLimit(key=key, count=1, window_start=now))
            db.commit()
            return Verdict(True)
        except IntegrityError:
            db.rollback()
    elif row[0] is not None and row[0] > now:
        return Verdict(False, int((row[0] - now).total_seconds()) + 1)

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
    bucket = db.get(RateLimit, key)
    if bucket is not None:
        db.delete(bucket)
        db.commit()


def sweep(db: OrmSession, older_than_hours: int = 24) -> int:
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
