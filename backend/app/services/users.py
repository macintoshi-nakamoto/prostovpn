from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import crypto, provisioning
from ..models import Plan, Provisioning, User, normalize_email, utcnow
from ..security import hash_password
from . import credentials
from .billing import grant_subscription
from .errors import PanelError
from . import keys as keys_service
from .keys import ensure_keys
from .translit import slugify

_LOGIN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_PASS_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_credentials(db: OrmSession, prefix: str = "user") -> tuple[str, str]:
    clean = slugify(prefix)
    for _ in range(50):
        tail = "".join(secrets.choice(_LOGIN_ALPHABET) for _ in range(6))
        login = f"{clean}-{tail}"
        if db.scalar(select(User).where(User.login == login)) is None:
            return login, generate_password()
    raise PanelError("не удалось подобрать свободный логин")


def login_from_hint(db: OrmSession, wanted: str | None) -> str | None:
    """
    Свободный логин по подсказке — юзернейму из Telegram.

    Человек знает себя по юзернейму, и логин «vanzero» он помнит наизусть,
    а выданный «vanzero-a3k9x2» — нет. Символы у юзернейма те же, что мы
    разрешаем в логине, так что берём его как есть; строчными, потому что
    логины сравниваются посимвольно, а Telegram регистра не различает.

    Пусто на выходе — значит подсказки не было или она не годится: зовущий
    оставляет прежний путь, транслит имени со случайным хвостом. Занятый
    юзернейм не повод отказываться: человек мог его сменить, а прежняя
    учётка с этим логином осталась — тогда добавляем короткий хвост.
    """
    clean = (wanted or "").strip().lstrip("@").lower()
    if not 3 <= len(clean) <= 60:
        return None
    if not all(ch.isascii() and (ch.isalnum() or ch in "-_.") for ch in clean):
        return None

    if db.scalar(select(User).where(User.login == clean)) is None:
        return clean
    for _ in range(20):
        tail = "".join(secrets.choice(_LOGIN_ALPHABET) for _ in range(4))
        candidate = f"{clean}-{tail}"
        if db.scalar(select(User).where(User.login == candidate)) is None:
            return candidate
    return None


def generate_password(length: int | None = None) -> str:
    if length is None:
        return credentials.gen_password()
    return "".join(secrets.choice(_PASS_ALPHABET) for _ in range(length))


def reveal_password(user: User) -> str:
    if not user.password_enc:
        raise PanelError(
            "пароль недоступен: учётка заведена до включения шифрования или ключ сменили. "
            "Остаётся сбросить пароль."
        )
    try:
        return crypto.decrypt(user.password_enc)
    except crypto.SecretsUnavailable as exc:
        raise PanelError(str(exc)) from exc


def create_user(
    db: OrmSession,
    login: str | None = None,
    password: str | None = None,
    days: int | None = None,
    plan_code: str | None = None,
    name: str | None = None,
    contact: str | None = None,
    note: str | None = None,
    traffic_limit_bytes: int | None = None,
    price: float | None = None,
    email: str | None = None,
) -> tuple[User, str, list[str]]:
    plan = None
    if plan_code:
        plan = db.scalar(select(Plan).where(Plan.code == plan_code))
        if plan is None:
            raise PanelError(f"тариф «{plan_code}» не найден")

    if login:
        login = login.strip()
        if not login:
            raise PanelError("логин не может быть пустым")
        if not all(ch.isascii() and (ch.isalnum() or ch in "-_.") for ch in login):
            raise PanelError(
                "в логине допустимы латинские буквы, цифры, дефис, точка и подчёркивание",
                "login_invalid",
            )
        if db.scalar(select(User).where(User.login == login)):
            raise PanelError(f"пользователь «{login}» уже есть", "login_taken")
        password = password or generate_password()
    else:
        login, generated = generate_credentials(db, prefix=(name or "user"))
        password = password or generated

    if len(password) < 4:
        raise PanelError("пароль короче четырёх символов")

    user = User(
        login=login,
        password_hash=hash_password(password),
        password_enc=crypto.encrypt_or_none(password),
        name=name,
        contact=contact,
        note=note,
        traffic_limit_bytes=traffic_limit_bytes,
    )
    user.set_email(email)
    db.add(user)
    db.commit()
    db.refresh(user)

    period = days if days is not None else (plan.period_days if plan else 30)
    if period > 0:
        grant_subscription(db, user, days=period, plan=plan, price=price)

    warnings = ensure_keys(db, user)
    db.refresh(user)
    return user, password, warnings


def find_by_email(db: OrmSession, address: str | None) -> User | None:
    normalized = normalize_email(address)
    if not normalized:
        return None
    user = db.scalar(select(User).where(User.email_hash == crypto.blind_index(normalized)))
    if user is None:
        user = db.scalar(select(User).where(User.email == normalized))
    return user


def set_password(db: OrmSession, user: User, password: str | None = None) -> str:
    value = password or generate_password()
    if len(value) < 4:
        raise PanelError("пароль короче четырёх символов")
    user.password_hash = hash_password(value)
    user.password_enc = crypto.encrypt_or_none(value)
    user.password_hint = None
    for session in user.sessions:
        if session.revoked_at is None:
            session.revoked_at = utcnow()
    db.commit()
    return value


def set_user_active(db: OrmSession, user: User, active: bool) -> list[str]:
    problems: list[str] = []
    user.is_active = active

    if not active:
        now = utcnow()
        for session in user.sessions:
            if session.revoked_at is None:
                session.revoked_at = now

        for key in user.keys:
            if key.revoked_at is not None:
                continue
            server = key.server
            if server.provisioning == Provisioning.SSH and key.public_key:
                try:
                    provisioning.remove_peer_over_ssh(
                        server, key.public_key, interface=keys_service.interface_for(db, key)
                    )
                except Exception as exc:
                    problems.append(f"{server.name}: {exc}")
                    continue
            key.revoked_at = now

    keys_service.xray_revoke(db, user.id)
    db.commit()

    if active:
        problems += ensure_keys(db, user)
        db.refresh(user)

    return problems


def block_user(db: OrmSession, user: User, reason: str | None = None) -> list[str]:
    problems: list[str] = []
    now = utcnow()

    user.is_blocked = True
    user.blocked_reason = reason
    user.blocked_at = now

    for session in user.sessions:
        if session.revoked_at is None:
            session.revoked_at = now

    for key in user.keys:
        if key.revoked_at is not None:
            continue
        server = key.server
        if server.provisioning == Provisioning.SSH and key.public_key:
            try:
                provisioning.remove_peer_over_ssh(
                    server, key.public_key, interface=keys_service.interface_for(db, key)
                )
            except Exception as exc:
                problems.append(f"{server.name}: {exc}")
                continue
        key.revoked_at = now

    keys_service.xray_revoke(db, user.id)
    db.commit()
    return problems


def unblock_user(db: OrmSession, user: User) -> list[str]:
    user.is_blocked = False
    user.blocked_reason = None
    user.blocked_at = None
    db.commit()
    warnings = ensure_keys(db, user)
    db.refresh(user)
    return warnings


def set_traffic_limit(
    db: OrmSession, user: User, limit_bytes: int | None, unlimited: bool = False
) -> None:
    if limit_bytes is not None and limit_bytes < 0:
        raise PanelError("лимит не может быть отрицательным")
    user.traffic_unlimited = unlimited
    user.traffic_limit_bytes = None if unlimited else limit_bytes
    db.commit()


def reset_traffic(db: OrmSession, user: User) -> None:
    user.traffic_used_bytes = 0
    user.traffic_reset_at = utcnow()
    db.commit()


def revoke_access(db: OrmSession, user: User, reason: str = "доступ отозван") -> list[str]:
    problems: list[str] = []
    now = utcnow()

    for sub in user.subscriptions:
        if sub.expires_at > now:
            sub.is_cancelled = True

    problems += block_user(db, user, reason=reason)
    user.is_active = False
    db.commit()
    return problems


def expire_overdue(db: OrmSession) -> int:
    now = utcnow()
    touched = 0
    for user in db.scalars(select(User).where(User.is_blocked.is_(False))):
        if user.active_subscription(now) is not None:
            continue
        live = [k for k in user.keys if k.revoked_at is None]
        if not live:
            continue
        for key in live:
            server = key.server
            if server.provisioning == Provisioning.SSH and key.public_key:
                try:
                    provisioning.remove_peer_over_ssh(
                        server, key.public_key, interface=keys_service.interface_for(db, key)
                    )
                except Exception:
                    continue
            key.revoked_at = now
        touched += 1
    if touched:
        db.commit()
    return touched


def days_left(user: User, now: dt.datetime | None = None) -> int | None:
    """Дней доступа для показа — по всей цепочке подписок."""
    return user.access_days_left_display(now)
