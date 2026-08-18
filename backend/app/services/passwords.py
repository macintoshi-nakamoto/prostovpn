"""
Сброс пароля по ссылке из письма.

Два правила, из которых следует всё остальное.

Первое: наружу нельзя показывать, есть ли такая почта. Ответ на просьбу
сбросить пароль одинаковый всегда — иначе форма превращается в проверялку
«зарегистрирован ли этот человек у вас», а это чужая приватность.

Второе: ссылка живёт полчаса и работает один раз. Письма пересылают,
показывают на экране и оставляют в открытой почте; вечная ссылка на смену
пароля — это вечный ключ от учётки.
"""

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

# Сколько живёт ссылка. Полчаса — столько же, сколько обещано в письме о
# подключённой почте; если менять, менять в обоих местах.
LIFETIME = dt.timedelta(minutes=30)


def request(db: OrmSession, email: str, ip: str | None = None) -> bool:
    """
    Заводит ссылку и ставит письмо в очередь. Возвращает, нашёлся ли человек.

    Ответ нужен вызывающему только для журнала: наружу он не уходит.
    """
    from .users import find_by_email

    user = find_by_email(db, email)
    if user is None:
        log.info("сброс пароля: почта не найдена")
        return False
    if user.is_blocked:
        # Заблокированному менять пароль незачем: войти он всё равно не
        # сможет, а письмо создаст ощущение, что доступ вот-вот вернётся.
        log.info("сброс пароля: учётка заблокирована, письмо не отправляем")
        return False

    # Прежние неиспользованные ссылки гасим: две живые ссылки на одну учётку
    # означают, что старая, уже кем-то подсмотренная, продолжает работать.
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
            requested_ip=ip,
        )
    )
    db.add(
        DeliveryJob(
            channel="email",
            template="password_reset",
            target=email,
            user_id=user.id,
            # В базе от ссылки лежит только хэш: сам токен существует ровно
            # до отправки письма, и передать его туда больше нечем.
            payload=token,
        )
    )
    db.commit()
    return True


def find(db: OrmSession, token: str) -> PasswordReset | None:
    """Живая ссылка по токену; None — нет такой, просрочена или использована."""
    entry = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_hash(token)))
    if entry is None or not entry.is_usable():
        return None
    return entry


def apply(db: OrmSession, token: str, password: str) -> User:
    """
    Меняет пароль по ссылке.

    `set_password` заодно гасит все живые входы — это не побочный эффект, а
    смысл: пароль меняют, когда старый мог утечь, и оставить работающими
    прежние сессии значит не сменить ничего.
    """
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
    """Убирает старые ссылки: держать их вечно незачем."""
    edge = utcnow() - dt.timedelta(days=older_than_days)
    rows = list(db.scalars(select(PasswordReset).where(PasswordReset.created_at < edge)))
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)
