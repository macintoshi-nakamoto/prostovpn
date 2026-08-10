"""
Вход: приложения клиентов и администраторы панели.

У обоих один приём — токен хранится хэшем, а не открытым текстом: утечка
базы не должна отдавать живые доступы.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import Admin, AdminSession, Session, User, utcnow
from ..security import hash_password, new_token, token_hash, verify_password
from .errors import PanelError


# --- вход из приложения ------------------------------------------------------


def authenticate(
    db: OrmSession,
    login: str,
    password: str,
    platform: str | None = None,
    app_version: str | None = None,
    ip: str | None = None,
) -> tuple[User, str]:
    """Проверяет пару логин/пароль и открывает сессию, вернув токен."""
    user = db.scalar(select(User).where(User.login == login.strip()))
    # Хэш считаем даже для несуществующего логина: иначе по времени ответа
    # видно, какие логины заведены.
    stored = user.password_hash if user else hash_password("dummy")
    ok = verify_password(password, stored)
    if not user or not ok:
        raise PanelError("неверный логин или пароль")
    if user.is_blocked:
        raise PanelError("доступ заблокирован")
    if not user.is_active:
        raise PanelError("доступ отключён")

    token = new_token()
    session = Session(
        user_id=user.id,
        token_hash=token_hash(token),
        platform=platform,
        app_version=app_version,
        ip=ip,
        expires_at=utcnow() + dt.timedelta(days=settings().client_token_days),
    )
    db.add(session)
    db.commit()
    return user, token


def session_for_token(db: OrmSession, token: str) -> Session | None:
    session = db.scalar(select(Session).where(Session.token_hash == token_hash(token)))
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


def touch(db: OrmSession, session: Session, ip: str | None = None) -> None:
    session.last_seen_at = utcnow()
    if ip:
        session.ip = ip
    db.commit()


# --- вход в панель -----------------------------------------------------------


def authenticate_admin(db: OrmSession, login: str, password: str) -> tuple[Admin, str, dt.datetime]:
    admin = db.scalar(select(Admin).where(Admin.login == login.strip()))
    stored = admin.password_hash if admin else hash_password("dummy")
    ok = verify_password(password, stored)
    if not admin or not ok:
        raise PanelError("неверный логин или пароль")

    token = new_token()
    expires_at = utcnow() + dt.timedelta(days=settings().admin_token_days)
    db.add(AdminSession(admin_id=admin.id, token_hash=token_hash(token), expires_at=expires_at))
    db.commit()
    return admin, token, expires_at


def admin_session_for_token(db: OrmSession, token: str) -> AdminSession | None:
    session = db.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash(token)))
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


def revoke_admin_session(db: OrmSession, session: AdminSession) -> None:
    session.revoked_at = utcnow()
    db.commit()
