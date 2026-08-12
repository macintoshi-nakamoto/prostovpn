"""
Логика панели: создание пользователей, раздача ключей, деньги.

Здесь же правило «сервер добавили — он появился у всех»: ключи не
привязаны к моменту регистрации пользователя, а досоздаются по факту.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from . import provisioning
from .config import settings
from .models import (
    Payment,
    Provisioning,
    Server,
    Session,
    Subscription,
    User,
    UserKey,
    utcnow,
)
from .security import hash_password, new_token, token_hash, verify_password


class PanelError(Exception):
    """Ошибка, которую можно показать администратору как есть."""


# --- пользователи и ключи ----------------------------------------------------


def active_servers(db: OrmSession) -> list[Server]:
    return list(
        db.scalars(
            select(Server).where(Server.is_active.is_(True)).order_by(Server.sort_order, Server.id)
        )
    )


def ensure_keys(db: OrmSession, user: User) -> list[str]:
    """
    Досоздаёт пользователю ключи на всех включённых серверах.

    Вызывается и при создании пользователя, и при добавлении сервера, и при
    каждом запросе списка серверов из приложения: так новый сервер
    появляется у всех сам, без ручной раздачи.

    Возвращает список предупреждений — сервер может быть недоступен, и это
    не повод валить всю операцию: остальные серверы человек получить должен.
    """
    warnings: list[str] = []
    existing = {key.server_id for key in user.keys if key.revoked_at is None}

    for server in active_servers(db):
        if server.id in existing:
            continue
        if server.provisioning == Provisioning.SHARED:
            # Общий ключ лежит на самом сервере, отдельная запись не нужна
            continue
        try:
            _issue_ssh_key(db, user, server)
        except Exception as exc:  # сервер недоступен или шаблон кривой
            warnings.append(f"{server.name}: {exc}")
    return warnings


def _issue_ssh_key(db: OrmSession, user: User, server: Server) -> UserKey:
    if not server.awg_template:
        raise PanelError("не задан шаблон конфига")

    private_key, public_key = provisioning.generate_keypair()

    taken = list(
        db.scalars(select(UserKey.address).where(UserKey.server_id == server.id, UserKey.address.is_not(None)))
    )
    address = provisioning.next_address(taken)
    config = provisioning.render_from_template(server.awg_template, private_key, address)

    provisioning.add_peer_over_ssh(server, public_key, address)

    key = UserKey(
        user_id=user.id,
        server_id=server.id,
        config=config,
        public_key=public_key,
        address=address,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


def create_user(
    db: OrmSession,
    login: str,
    password: str,
    days: int = 30,
    plan: str = "basic",
    note: str | None = None,
) -> tuple[User, list[str]]:
    login = login.strip()
    if not login:
        raise PanelError("логин не может быть пустым")
    if db.scalar(select(User).where(User.login == login)):
        raise PanelError(f"пользователь «{login}» уже есть")
    if len(password) < 4:
        raise PanelError("пароль короче четырёх символов")

    user = User(login=login, password_hash=hash_password(password), note=note)
    db.add(user)
    db.commit()
    db.refresh(user)

    if days > 0:
        grant_subscription(db, user, days=days, plan=plan)

    warnings = ensure_keys(db, user)
    db.refresh(user)
    return user, warnings


def grant_subscription(db: OrmSession, user: User, days: int, plan: str = "basic") -> Subscription:
    """
    Продлевает доступ. Если подписка ещё жива — продлеваем от её конца, а не
    от сегодняшнего дня: оплата не должна съедать оставшиеся дни.
    """
    now = utcnow()
    current = user.active_subscription(now)
    starts = current.expires_at if current else now
    sub = Subscription(
        user_id=user.id, plan=plan, starts_at=starts, expires_at=starts + dt.timedelta(days=days)
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def revoke_access(db: OrmSession, user: User) -> list[str]:
    """Снимает доступ: гасит подписки, сессии и убирает пиров с серверов."""
    problems: list[str] = []
    now = utcnow()

    for sub in user.subscriptions:
        if sub.expires_at > now:
            sub.is_cancelled = True
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

    user.is_active = False
    db.commit()
    return problems


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


# --- деньги ------------------------------------------------------------------


def add_payment(
    db: OrmSession,
    amount: Decimal | float | str,
    user: User | None = None,
    method: str | None = None,
    comment: str | None = None,
    paid_at: dt.datetime | None = None,
    currency: str | None = None,
    external_id: str | None = None,
) -> Payment:
    value = Decimal(str(amount))
    if value <= 0:
        raise PanelError("сумма должна быть больше нуля")
    payment = Payment(
        user_id=user.id if user else None,
        amount=value,
        currency=currency or settings().currency,
        method=method,
        comment=comment,
        external_id=external_id,
        paid_at=paid_at or utcnow(),
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def revenue_series(db: OrmSession, days: int = 30) -> list[tuple[str, Decimal]]:
    """Выручка по дням за последние `days` дней, включая нулевые дни."""
    since = utcnow() - dt.timedelta(days=days - 1)
    rows = db.execute(select(Payment.paid_at, Payment.amount).where(Payment.paid_at >= since)).all()

    totals: dict[str, Decimal] = defaultdict(Decimal)
    for paid_at, amount in rows:
        totals[paid_at.date().isoformat()] += Decimal(str(amount))

    today = utcnow().date()
    return [
        ((today - dt.timedelta(days=offset)).isoformat(), totals[(today - dt.timedelta(days=offset)).isoformat()])
        for offset in range(days - 1, -1, -1)
    ]


def revenue_by_month(db: OrmSession, months: int = 12) -> list[tuple[str, Decimal]]:
    rows = db.execute(select(Payment.paid_at, Payment.amount)).all()
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for paid_at, amount in rows:
        totals[f"{paid_at.year:04d}-{paid_at.month:02d}"] += Decimal(str(amount))

    today = utcnow().date()
    keys: list[str] = []
    year, month = today.year, today.month
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return [(key, totals[key]) for key in reversed(keys)]


def revenue_by_year(db: OrmSession) -> list[tuple[str, Decimal]]:
    rows = db.execute(select(Payment.paid_at, Payment.amount)).all()
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for paid_at, amount in rows:
        totals[str(paid_at.year)] += Decimal(str(amount))
    return sorted(totals.items())


def dashboard_totals(db: OrmSession) -> dict[str, object]:
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def total(since: dt.datetime) -> Decimal:
        value = db.scalar(select(func.sum(Payment.amount)).where(Payment.paid_at >= since))
        return Decimal(str(value)) if value is not None else Decimal(0)

    users = list(db.scalars(select(User)))
    online_since = now - dt.timedelta(minutes=10)

    return {
        "users_total": len(users),
        "users_active": sum(1 for u in users if u.has_access(now)),
        "servers_total": db.scalar(select(func.count()).select_from(Server)) or 0,
        "sessions_online": db.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.last_seen_at >= online_since, Session.revoked_at.is_(None))
        )
        or 0,
        "revenue_day": total(day_start),
        "revenue_month": total(month_start),
        "revenue_year": total(year_start),
        "currency": settings().currency,
    }
