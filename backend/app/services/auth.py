from __future__ import annotations

import datetime as dt
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import Admin, AdminSession, Session, User, sanitize_device_id, utcnow
from ..security import (
    hash_password,
    ip_tag,
    needs_rehash,
    new_token,
    token_hash,
    verify_password,
)
from . import ratelimit
from .errors import PanelError

log = logging.getLogger("panel.auth")

BAD_CREDENTIALS = "неверный логин или пароль"

_DUMMY_HASH = hash_password(secrets.token_hex(32))


class LoginThrottled(PanelError):

    def __init__(self, retry_after: int) -> None:
        minutes = max(1, round(retry_after / 60))
        super().__init__(
            f"слишком много попыток входа, попробуйте через {minutes} мин", "throttled"
        )
        self.retry_after = retry_after


BY_NAME_FACTOR = 4
BY_IP_FACTOR = 10


def _norm_login(login: str) -> str:
    return login.strip().lower()[:64]


def _login_key(login: str, ip: str | None) -> str:
    return f"login:{ip_tag(ip)}:{_norm_login(login)}"


def _login_name_key(login: str) -> str:
    return f"login:*:{_norm_login(login)}"


def _login_ip_key(ip: str | None) -> str:
    return f"login-ip:{ip_tag(ip)}"


def reset_login_throttle(db: OrmSession, login: str, ip: str | None) -> None:
    ratelimit.clear(db, _login_key(login, ip))
    ratelimit.clear(db, _login_name_key(login))


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
    config = settings()
    key = _login_key(login, ip)
    name_key = _login_name_key(login)
    ip_key = _login_ip_key(ip)

    verdict = ratelimit.hit(
        db,
        key,
        limit=config.login_max_attempts,
        window_minutes=config.login_window_minutes,
        lock_minutes=config.login_lock_minutes,
    )
    # Замок по одному логину считает только промахи и запирает только их:
    # иначе чужие попытки с пары адресов запирали бы хозяина с верным
    # паролем. Верный пароль проходит всегда, промах под замком — нет.
    name_verdict = ratelimit.check(db, name_key)
    if verdict.allowed:
        verdict = ratelimit.check(db, ip_key)
    if not verdict.allowed:
        log.warning("вход заперт по частоте")
        raise LoginThrottled(verdict.retry_after)

    user = db.scalar(select(User).where(User.login == login.strip()))
    stored = user.password_hash if user else _DUMMY_HASH
    ok = verify_password(password, stored)
    if not user or not ok:
        if user is not None:
            user.failed_logins += 1
        ratelimit.hit(
            db,
            ip_key,
            limit=config.login_max_attempts * BY_IP_FACTOR,
            window_minutes=config.login_window_minutes,
            lock_minutes=config.login_lock_minutes,
        )
        ratelimit.hit(
            db,
            name_key,
            limit=config.login_max_attempts * BY_NAME_FACTOR,
            window_minutes=config.login_window_minutes * BY_NAME_FACTOR,
            lock_minutes=config.login_lock_minutes,
        )
        db.commit()
        if not name_verdict.allowed:
            raise LoginThrottled(name_verdict.retry_after)
        raise PanelError(BAD_CREDENTIALS, "bad_credentials")

    if user.is_blocked:
        raise PanelError("доступ заблокирован", "blocked")
    if not user.is_active:
        raise PanelError("доступ отключён", "disabled")

    ratelimit.clear(db, key)
    ratelimit.clear(db, name_key)
    user.failed_logins = 0
    user.last_login_at = utcnow()

    if needs_rehash(stored):
        user.password_hash = hash_password(password)

    token = open_session(
        db, user, platform=platform, app_version=app_version, device_id=device_id
    )
    session = db.scalar(select(Session).where(Session.token_hash == token_hash(token)))
    _enforce_device_limit(db, user, session)
    return user, token


def open_session(
    db: OrmSession,
    user: User,
    *,
    platform: str | None = None,
    app_version: str | None = None,
    device_id: str | None = None,
) -> str:
    """Выдаёт токен сессии без проверки пароля — для входов, где личность
    уже удостоверена иначе (подпись Telegram). Лимит устройств здесь не
    проверяется: звать отдельно, если вход претендует на слот."""
    token = new_token()
    db.add(
        Session(
            user_id=user.id,
            token_hash=token_hash(token),
            platform=platform,
            app_version=app_version,
            ip=None,
            device_id=sanitize_device_id(device_id),
            device_name=None,
            expires_at=utcnow() + dt.timedelta(days=settings().client_token_days),
        )
    )
    db.commit()
    return token


def _enforce_device_limit(db: OrmSession, user: User, current: Session) -> None:
    now = utcnow()
    live = [s for s in user.live_sessions() if s.id != current.id]

    if current.device_id:
        for session in live:
            if session.device_id == current.device_id:
                session.revoked_at = now
        live = [s for s in live if s.device_id != current.device_id]

    if not current.is_device:
        db.commit()
        return

    limit = user.device_limit()
    if limit <= 0:
        db.commit()
        return

    # В лимит входят не только входы приложения: ключи iPhone и ссылки для
    # Happ занимают по месту каждый. Лишние входы приложения снимаем — новый
    # вход побеждает старый, так было всегда. А ключ или ссылку с телефона
    # снять отсюда нельзя (человек их вставлял руками), поэтому если мест
    # не хватает даже после этого — вход не проходит, и приложение говорит,
    # что освободить.
    devices = [s for s in live if s.is_device]
    fixed = len(user.ios_slots_live()) + len(user.subscription_links_live(now))
    excess = len(devices) + fixed + 1 - limit
    if excess > 0:
        from .devices import disconnect

        for session in sorted(devices, key=lambda s: s.last_seen_at)[:excess]:
            disconnect(db, session, reason="лимит тарифа")
            log.info("устройство отвязано по лимиту тарифа: пользователь %s", user.public_id)
            excess -= 1
    if excess > 0:
        current.revoked_at = now
        db.commit()
        log.info("вход отклонён по лимиту устройств: пользователь %s", user.public_id)
        raise PanelError(
            f"по тарифу доступно устройств: {limit}, и все заняты. Отключите "
            "ненужное устройство в кабинете или выберите тариф больше",
            "device_limit",
        )
    db.commit()


def session_for_token(db: OrmSession, token: str) -> Session | None:
    session = db.scalar(select(Session).where(Session.token_hash == token_hash(token)))
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


def touch(db: OrmSession, session: Session, ip: str | None = None) -> None:
    now = utcnow()
    session.last_seen_at = now

    full = dt.timedelta(days=settings().client_token_days)
    if session.expires_at - now < full / 2:
        session.expires_at = now + full
    db.commit()


ADMIN_BY_NAME_FACTOR = 10


def _admin_key(login: str, ip: str | None) -> str:
    return f"admin-login:{ip_tag(ip)}:{_norm_login(login)}"


def _admin_name_key(login: str) -> str:
    return f"admin-login:*:{_norm_login(login)}"


def _admin_ip_key(ip: str | None) -> str:
    return f"admin-login-ip:{ip_tag(ip)}"


def authenticate_admin(
    db: OrmSession, login: str, password: str, ip: str | None = None
) -> tuple[Admin, str, dt.datetime]:
    config = settings()
    key = _admin_key(login, ip)
    name_key = _admin_name_key(login)
    ip_key = _admin_ip_key(ip)

    verdict = ratelimit.hit(
        db,
        key,
        limit=config.login_max_attempts,
        window_minutes=config.login_window_minutes,
        lock_minutes=config.login_lock_minutes,
    )
    # Как и у клиентов: замок по имени — только для промахов, хозяина с
    # верным паролем чужой перебор не запирает.
    name_verdict = ratelimit.check(db, name_key)
    if verdict.allowed:
        verdict = ratelimit.check(db, ip_key)
    if not verdict.allowed:
        log.warning("вход в панель заперт по частоте")
        raise LoginThrottled(verdict.retry_after)

    admin = db.scalar(select(Admin).where(Admin.login == login.strip()))
    stored = admin.password_hash if admin else _DUMMY_HASH
    ok = verify_password(password, stored)
    if not admin or not ok:
        ratelimit.hit(
            db,
            ip_key,
            limit=config.login_max_attempts * BY_IP_FACTOR,
            window_minutes=config.login_window_minutes,
            lock_minutes=config.login_lock_minutes,
        )
        ratelimit.hit(
            db,
            name_key,
            limit=config.login_max_attempts * ADMIN_BY_NAME_FACTOR,
            window_minutes=config.login_window_minutes * BY_NAME_FACTOR,
            lock_minutes=config.login_lock_minutes,
        )
        if not name_verdict.allowed:
            raise LoginThrottled(name_verdict.retry_after)
        raise PanelError("неверный логин или пароль")

    ratelimit.clear(db, key)
    ratelimit.clear(db, name_key)

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
