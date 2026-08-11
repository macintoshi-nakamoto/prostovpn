"""
Пользователи: создание с готовыми доступами, блокировки, лимиты трафика.

Логин и пароль генерирует панель, а не клиент: человеку их называют уже
готовыми, и слабых паролей в системе не появляется.
"""

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
from .keys import ensure_keys
from .translit import slugify

# Без похожих символов: то, что диктуют голосом, не должно путаться.
_LOGIN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_PASS_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_credentials(db: OrmSession, prefix: str = "user") -> tuple[str, str]:
    """
    Свободный логин и пароль к нему.

    Логин проверяем по базе в цикле: коллизия на шести символах редка, но
    «редка» и «невозможна» — разные вещи, а падать при создании нельзя.
    """
    clean = slugify(prefix)
    for _ in range(50):
        tail = "".join(secrets.choice(_LOGIN_ALPHABET) for _ in range(6))
        login = f"{clean}-{tail}"
        if db.scalar(select(User).where(User.login == login)) is None:
            return login, generate_password()
    raise PanelError("не удалось подобрать свободный логин")


def generate_password(length: int | None = None) -> str:
    """
    Пароль в том же виде, что выдаёт сайт: `k3np-7hqm-2rxa`.

    Единый вид для учёток из панели и с сайта — не косметика. Поддержка
    диктует пароль голосом, и группами по четыре он проговаривается без
    «эс как доллар, потом большая и»; длинная строка вперемешку регистров
    этого не позволяет. `length` оставлен ради старых вызовов и означает
    произвольную длину прежним алфавитом.
    """
    if length is None:
        return credentials.gen_password()
    return "".join(secrets.choice(_PASS_ALPHABET) for _ in range(length))


def reveal_password(user: User) -> str:
    """
    Расшифровывает пароль для показа администратору.

    Вызывается ровно из одного места админского API, и то место обязано
    записать факт показа в журнал: после выдачи это единственный способ
    узнать пароль, и он должен оставлять след.
    """
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
    """
    Заводит клиента и сразу выдаёт ему ключи на все включённые серверы.

    Возвращает пользователя, пароль открытым текстом (единственный момент,
    когда его вообще можно показать) и список предупреждений по серверам.
    """
    plan = None
    if plan_code:
        plan = db.scalar(select(Plan).where(Plan.code == plan_code))
        if plan is None:
            raise PanelError(f"тариф «{plan_code}» не найден")

    if login:
        login = login.strip()
        if not login:
            raise PanelError("логин не может быть пустым")
        # Логин набирают руками в приложении: кириллица и пробелы в нём
        # оборачиваются жалобой «не могу войти», а причина не видна.
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
        # Открытым текстом пароль в базе не лежит: только хэш для входа и
        # шифротекст для показа администратору, см. crypto.py.
        password_enc=crypto.encrypt_or_none(password),
        email=normalize_email(email),
        name=name,
        contact=contact,
        note=note,
        traffic_limit_bytes=traffic_limit_bytes,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    period = days if days is not None else (plan.period_days if plan else 30)
    if period > 0:
        grant_subscription(db, user, days=period, plan=plan, price=price)

    warnings = ensure_keys(db, user)
    db.refresh(user)
    return user, password, warnings


def set_password(db: OrmSession, user: User, password: str | None = None) -> str:
    """Меняет пароль и возвращает его открытым текстом для передачи клиенту."""
    value = password or generate_password()
    if len(value) < 4:
        raise PanelError("пароль короче четырёх символов")
    user.password_hash = hash_password(value)
    user.password_enc = crypto.encrypt_or_none(value)
    user.password_hint = None
    # Старые входы после смены пароля больше не действуют.
    for session in user.sessions:
        if session.revoked_at is None:
            session.revoked_at = utcnow()
    db.commit()
    return value


def set_user_active(db: OrmSession, user: User, active: bool) -> list[str]:
    """
    Пауза доступа — с немедленным разрывом туннеля.

    Раньше здесь гасились только сессии, а пиры оставались на узлах.
    Выглядело это так: администратор нажимает «отключить», в панели
    загорается «отключён», а человек продолжает сидеть в интернете через
    наш сервер — сессия приложения нужна только чтобы спросить список
    серверов, а уже установленный туннель живёт сам по себе. Доступ
    закрывался в лучшем случае при следующем запуске приложения.

    Поэтому пир снимается сразу. Обратное включение заново его выдаёт:
    `unblock_user` и `ensure_keys` для того и существуют, а переиздание
    пары ключей стоит одного захода по SSH.

    Возвращает список узлов, с которых пира снять не удалось, — чтобы
    администратор знал, где доступ ещё остался.
    """
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
                    provisioning.remove_peer_over_ssh(server, key.public_key)
                except Exception as exc:
                    problems.append(f"{server.name}: {exc}")
                    continue
            key.revoked_at = now

    db.commit()

    if active:
        # Включаем обратно — возвращаем и пиры, иначе человек войдёт в
        # приложение и увидит пустой список стран.
        problems += ensure_keys(db, user)
        db.refresh(user)

    return problems


def block_user(db: OrmSession, user: User, reason: str | None = None) -> list[str]:
    """
    Бан: вход запрещён, сессии погашены, пиры сняты с серверов.

    Возвращает список серверов, с которых пира снять не удалось — чтобы
    администратор знал, где остался доступ.
    """
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
                provisioning.remove_peer_over_ssh(server, key.public_key)
            except Exception as exc:
                problems.append(f"{server.name}: {exc}")
                continue
        key.revoked_at = now

    db.commit()
    return problems


def unblock_user(db: OrmSession, user: User) -> list[str]:
    """Снимает бан и заново выдаёт ключи на действующих серверах."""
    user.is_blocked = False
    user.blocked_reason = None
    user.blocked_at = None
    db.commit()
    warnings = ensure_keys(db, user)
    db.refresh(user)
    return warnings


def set_traffic_limit(db: OrmSession, user: User, limit_bytes: int | None) -> None:
    """`None` — безлимит. Отдельного флага нет: отсутствие лимита и есть он."""
    if limit_bytes is not None and limit_bytes < 0:
        raise PanelError("лимит не может быть отрицательным")
    user.traffic_limit_bytes = limit_bytes
    db.commit()


def reset_traffic(db: OrmSession, user: User) -> None:
    """
    Обнуляет расход — обычно при продлении на новый период.

    Абсолютные счётчики пиров не трогаем: следующий замер сравнивается с
    ними, и обнуление здесь не должно превратиться в фантомный прирост.
    """
    user.traffic_used_bytes = 0
    user.traffic_reset_at = utcnow()
    db.commit()


def revoke_access(db: OrmSession, user: User, reason: str = "доступ отозван") -> list[str]:
    """Снимает доступ: гасит подписки, сессии и убирает пиров с серверов."""
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
    """
    Снимает пиров у тех, чья подписка кончилась.

    Вызывается по расписанию: без этого неоплаченный пользователь продолжает
    ходить по уже выданному конфигу, пока приложение не спросит серверы.
    """
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
                    provisioning.remove_peer_over_ssh(server, key.public_key)
                except Exception:
                    continue
            key.revoked_at = now
        touched += 1
    if touched:
        db.commit()
    return touched


def days_left(user: User, now: dt.datetime | None = None) -> int | None:
    sub = user.active_subscription(now)
    if sub is None:
        return None
    return max(0, (sub.expires_at - (now or utcnow())).days)
