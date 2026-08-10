"""
Вход: приложения клиентов и администраторы панели.

У обоих один приём — токен хранится хэшем, а не открытым текстом: утечка
базы не должна отдавать живые доступы.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import Admin, AdminSession, Session, User, utcnow
from ..security import hash_password, needs_rehash, new_token, token_hash, verify_password
from . import ratelimit
from .errors import PanelError

log = logging.getLogger("panel.auth")

# Один и тот же текст на «нет такого логина» и «пароль не тот». Разные
# формулировки превращают форму входа в справочник существующих логинов.
BAD_CREDENTIALS = "неверный логин или пароль"


class LoginThrottled(PanelError):
    """Слишком много попыток. `retry_after` — через сколько секунд можно."""

    def __init__(self, retry_after: int) -> None:
        minutes = max(1, round(retry_after / 60))
        super().__init__(f"слишком много попыток входа, попробуйте через {minutes} мин")
        self.retry_after = retry_after


# --- вход из приложения ------------------------------------------------------


def _login_key(login: str, ip: str | None) -> str:
    return f"login:{ip or 'unknown'}:{login.strip().lower()[:64]}"


def authenticate(
    db: OrmSession,
    login: str,
    password: str,
    platform: str | None = None,
    app_version: str | None = None,
    ip: str | None = None,
    device_id: str | None = None,
    device_name: str | None = None,
) -> tuple[User, str]:
    """Проверяет пару логин/пароль и открывает сессию, вернув токен."""
    config = settings()
    key = _login_key(login, ip)

    verdict = ratelimit.hit(
        db,
        key,
        limit=config.login_max_attempts,
        window_minutes=config.login_window_minutes,
        lock_minutes=config.login_lock_minutes,
    )
    if not verdict.allowed:
        log.warning("вход заперт: %s", key)
        raise LoginThrottled(verdict.retry_after)

    user = db.scalar(select(User).where(User.login == login.strip()))
    # Хэш считаем даже для несуществующего логина: иначе по времени ответа
    # видно, какие логины заведены.
    stored = user.password_hash if user else hash_password("dummy")
    ok = verify_password(password, stored)
    if not user or not ok:
        if user is not None:
            user.failed_logins += 1
            db.commit()
        raise PanelError(BAD_CREDENTIALS)

    if user.is_locked_out():
        raise LoginThrottled(int((user.locked_until - utcnow()).total_seconds()) + 1)
    if user.is_blocked:
        raise PanelError("доступ заблокирован")
    if not user.is_active:
        raise PanelError("доступ отключён")

    ratelimit.clear(db, key)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()

    # Пароль есть открытым текстом только здесь и только сейчас — другого
    # повода перевести старый scrypt-хэш на argon2id не будет.
    if needs_rehash(stored):
        user.password_hash = hash_password(password)

    token = new_token()
    session = Session(
        user_id=user.id,
        token_hash=token_hash(token),
        platform=platform,
        app_version=app_version,
        ip=ip,
        device_id=device_id,
        device_name=device_name,
        expires_at=utcnow() + dt.timedelta(days=config.client_token_days),
    )
    db.add(session)
    db.commit()

    _enforce_device_limit(db, user, session)
    return user, token


def _enforce_device_limit(db: OrmSession, user: User, current: Session) -> None:
    """
    Держит число устройств в пределах тарифа.

    Вход не запрещаем, а гасим самый старый сеанс. Отказать человеку,
    который только что заплатил, потому что он забыл выйти на старом
    телефоне, — верный способ получить обращение в поддержку вместо
    работающего сервиса. Тот, кого выкинули, увидит это на своём устройстве
    и войдёт заново, если оно ему нужно.
    """
    limit = user.device_limit()
    if limit <= 0:
        return

    live = [s for s in user.live_sessions() if s.id != current.id]

    # Повторный вход с того же устройства — не второе устройство. Гасим
    # прежний сеанс этой установки, чтобы переустановка не съедала лимит.
    if current.device_id:
        same = [s for s in live if s.device_id == current.device_id]
        for session in same:
            session.revoked_at = utcnow()
        live = [s for s in live if s.device_id != current.device_id]

    excess = len(live) + 1 - limit
    if excess > 0:
        for session in sorted(live, key=lambda s: s.last_seen_at)[:excess]:
            session.revoked_at = utcnow()
            log.info("устройство отвязано по лимиту тарифа: пользователь %s", user.public_id)
    db.commit()


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
