from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import DeliveryJob, PasswordReset, User, utcnow
from ..security import new_token, token_hash
from .errors import PanelError
from .users import set_password

log = logging.getLogger("panel.passwords")

LIFETIME = dt.timedelta(minutes=30)


def request(db: OrmSession, email: str, ip: str | None = None) -> bool:
    from .users import find_by_email

    user = find_by_email(db, email)
    if user is None:
        log.info("сброс пароля: почта не найдена")
        return False
    if user.is_blocked:
        log.info("сброс пароля: учётка заблокирована, письмо не отправляем")
        return False

    for old in db.scalars(
        select(PasswordReset).where(
            PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
        )
    ):
        old.used_at = utcnow()

    token = new_token()
    db.add(
        PasswordReset(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=utcnow() + LIFETIME,
            requested_ip=None,
        )
    )
    db.add(
        DeliveryJob(
            channel="email",
            template="password_reset",
            target=email,
            user_id=user.id,
            payload=token,
        )
    )
    db.commit()
    return True


def find(db: OrmSession, token: str) -> PasswordReset | None:
    entry = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_hash(token)))
    if entry is None or not entry.is_usable():
        return None
    return entry


def apply(db: OrmSession, token: str, password: str) -> User:
    entry = find(db, token)
    if entry is None:
        raise PanelError("ссылка недействительна или уже использована")
    if len(password) < 8:
        raise PanelError("пароль короче восьми символов")

    user = entry.user
    set_password(db, user, password)
    entry.used_at = utcnow()
    db.commit()
    log.info("пароль сменён по ссылке для %s", user.public_id)
    return user


def sweep(db: OrmSession, older_than_days: int = 7) -> int:
    edge = utcnow() - dt.timedelta(days=older_than_days)
    rows = list(db.scalars(select(PasswordReset).where(PasswordReset.created_at < edge)))
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)
