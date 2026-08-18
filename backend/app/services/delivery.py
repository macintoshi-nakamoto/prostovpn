"""
Обходчик очереди доставки.

Задание на письмо создаётся в той же транзакции, что и подписка, — это
транзакционный outbox: либо выдача и обещание доставить записаны вместе,
либо не записано ничего. Отправка происходит здесь, отдельно и после
коммита, потому что почтовый сервер отвечает секундами, а иногда не
отвечает вовсе.

Пароль в задании не хранится. Отправитель берёт `users.password_enc` и
расшифровывает его в момент отправки, а переменную с открытым текстом
никуда не пишет. Поэтому в логах очереди пароля нет и появиться не может:
в них просто нечего писать.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as OrmSession

from .. import crypto
from ..config import settings
from ..models import DeliveryJob, User, utcnow
from . import mail, telegram

log = logging.getLogger("panel.delivery")

# Пауза перед повтором: 1, 2, 4, ... минут, но не больше часа. Почтовый
# сервис, упавший на пять минут, не должен получить от нас двести попыток.
_BACKOFF_BASE_MINUTES = 1
_BACKOFF_CAP_MINUTES = 60


def pending(db: OrmSession, limit: int = 20) -> list[DeliveryJob]:
    now = utcnow()
    return list(
        db.scalars(
            select(DeliveryJob)
            .where(
                DeliveryJob.sent_at.is_(None),
                DeliveryJob.next_attempt_at <= now,
                DeliveryJob.attempts < settings().delivery_max_attempts,
            )
            .order_by(DeliveryJob.next_attempt_at)
            .limit(limit)
        )
    )


def run_once(db: OrmSession, limit: int = 20) -> int:
    """Разгребает очередь. Возвращает число доставленных заданий."""
    delivered = 0
    for job in pending(db, limit):
        if _deliver(db, job):
            delivered += 1
    return delivered


def _deliver(db: OrmSession, job: DeliveryJob) -> bool:
    job.attempts += 1
    try:
        _send(db, job)
    except Exception as exc:
        job.last_error = str(exc)[:500]
        job.next_attempt_at = utcnow() + _backoff(job.attempts)
        db.commit()
        remaining = settings().delivery_max_attempts - job.attempts
        log.warning(
            "доставка %s#%d на %s не удалась (%s), попыток осталось %d",
            job.channel,
            job.id,
            _mask(job.target),
            exc,
            max(0, remaining),
        )
        return False

    job.sent_at = utcnow()
    job.last_error = None
    db.commit()
    log.info("доставлено: %s#%d → %s", job.channel, job.id, _mask(job.target))
    return True


def _backoff(attempt: int) -> dt.timedelta:
    minutes = min(_BACKOFF_BASE_MINUTES * 2 ** max(0, attempt - 1), _BACKOFF_CAP_MINUTES)
    return dt.timedelta(minutes=minutes)


def _mask(target: str) -> str:
    """
    Адрес в логе — частично. Полный список почт клиентов в журнале сервера
    не нужен никому, кроме того, кто до этого журнала доберётся.
    """
    if "@" not in target:
        return target[:3] + "***"
    name, _, domain = target.partition("@")
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}***@{domain}"


def _send(db: OrmSession, job: DeliveryJob) -> None:
    user = db.get(User, job.user_id) if job.user_id else None
    if user is None:
        raise RuntimeError("пользователь удалён, доставлять некому")

    expires = _expires_label(user)
    site = settings().site_url.rstrip("/")
    # Человеку с iPhone к логину и паролю нужна дорога до ключа AmneziaVPN:
    # приложения там нет, и без этой строки письмо ведёт в пустоту.
    ios = user.ios_access

    if job.channel == "email":
        if job.template == "credentials":
            text, html = mail.credentials_body(user.login, _password(user), expires, ios=ios)
        else:
            text, html = mail.renewed_body(user.login, expires, ios=ios)
        mail.send(job.target, settings().mail_subject, text, html)
        return

    if job.channel == "telegram":
        if job.template == "credentials":
            body = telegram.credentials_text(user.login, _password(user), expires, site, ios=ios)
        else:
            body = telegram.renewed_text(user.login, expires, site, ios=ios)
        telegram.send(job.target, body)
        return

    raise RuntimeError(f"неизвестный канал доставки {job.channel!r}")


def _password(user: User) -> str:
    """
    Пароль для письма. Единственное место, где он выходит из шифра.

    Если ключа нет, письмо без пароля бессмысленно — лучше честно уронить
    задание в очередь с понятной ошибкой, чем отправить человеку письмо с
    пустым полем и оставить его без доступа.
    """
    if not user.password_enc:
        raise RuntimeError(
            "пароль не сохранён (PANEL_SECRETS_KEY не задан) — сбросьте пароль в панели"
        )
    try:
        return crypto.decrypt(user.password_enc)
    except crypto.SecretsUnavailable as exc:
        raise RuntimeError(f"пароль не расшифровывается: {exc}") from exc


def _expires_label(user: User) -> str:
    subscription = user.active_subscription()
    if subscription is None:
        return "—"
    return subscription.expires_at.strftime("%d.%m.%Y")


def stuck(db: OrmSession) -> list[DeliveryJob]:
    """
    Задания, которые исчерпали попытки. Их видно в панели: человек заплатил,
    а доступ до него не дошёл — это разбирают руками, а не забывают.
    """
    return list(
        db.scalars(
            select(DeliveryJob)
            .where(
                DeliveryJob.sent_at.is_(None),
                or_(
                    DeliveryJob.attempts >= settings().delivery_max_attempts,
                    DeliveryJob.attempts >= 3,
                ),
            )
            .order_by(DeliveryJob.created_at.desc())
        )
    )


def retry(db: OrmSession, job: DeliveryJob) -> None:
    """Ручной повтор из панели: сбрасывает счётчик и отправляет сейчас."""
    job.attempts = 0
    job.next_attempt_at = utcnow()
    job.last_error = None
    db.commit()
    _deliver(db, job)
