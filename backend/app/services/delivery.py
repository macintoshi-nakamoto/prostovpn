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
from . import letters, mail, telegram

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
        # Письма по макетам сами знают свою тему: «Чек об оплате — 2 028 ₽»
        # в списке писем говорит больше, чем одинаковая строка на всё.
        letter = _letter(db, job, user)
        if letter is not None:
            subject, text, html = letter
            mail.send(job.target, subject, text, html)
            return

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


# За сколько дней до конца подписки предупреждаем.
#
# Три — из макета письма, и число разумное: за три дня человек успевает
# решить, продлевать ли, но ещё не забывает, о чём речь. Раньше — письмо
# приходит в пустоту, позже — человек узнаёт об отключении по факту.
REMIND_DAYS_BEFORE = 3


def queue_expiry_reminders(db: OrmSession) -> int:
    """
    Ставит в очередь по одному напоминанию на подписку, которой скоро конец.

    Одно на подписку и навсегда: пометка `reminder_sent_at` не даёт слать его
    при каждом обходе, а продление заводит НОВУЮ строку подписки, у которой
    пометки нет, — поэтому следующий срок снова будет предупреждён.

    Пишем только тем, у кого есть почта. Отсутствие адреса — не ошибка:
    учётку могли завести из панели или из бота, и напоминать там нечем.

    Возвращает, сколько писем поставлено.
    """
    from ..models import Subscription

    now = utcnow()
    edge = now + dt.timedelta(days=REMIND_DAYS_BEFORE)
    rows = db.scalars(
        select(Subscription).where(
            Subscription.reminder_sent_at.is_(None),
            Subscription.is_cancelled.is_(False),
            Subscription.expires_at > now,
            Subscription.expires_at <= edge,
        )
    )

    queued = 0
    for subscription in rows:
        user = subscription.user
        if user is None:
            continue
        address = user.email_plain
        if not address:
            # Пометку всё равно ставим: иначе эта подписка будет попадать в
            # выборку каждый обход до самого конца срока.
            subscription.reminder_sent_at = now
            continue
        db.add(
            DeliveryJob(
                channel="email",
                template="reminder",
                target=address,
                user_id=user.id,
            )
        )
        subscription.reminder_sent_at = now
        queued += 1

    if queued or rows:
        db.commit()
    return queued


def _letter(db: OrmSession, job: DeliveryJob, user: User):
    """
    Готовое письмо по макету или None, если для этого вида его нет.

    None означает «дальше по-старому»: доступы и продление уходят прежними
    текстовыми письмами. Разом переводить на макеты всё нельзя — в них нет
    ни логина с паролем, ни ссылки на ключ для iPhone.
    """
    if job.template == "receipt":
        return _receipt_letter(db, job, user)
    if job.template == "email_attached":
        return letters.email_attached(email=job.target)
    if job.template == "reminder":
        return _reminder_letter(user)
    return None


def _receipt_letter(db: OrmSession, job: DeliveryJob, user: User):
    """
    Чек по последней оплате заказа.

    Берём именно платёж, а не заказ: в заказе сумма к оплате, а в платеже —
    та, что действительно списана. Расходятся они редко, но чек обязан
    показывать второе.
    """
    from ..models import Payment

    payment = db.scalar(
        select(Payment)
        .where(Payment.order_id == job.order_id)
        .order_by(Payment.paid_at.desc())
    ) if job.order_id else None
    if payment is None:
        payment = db.scalar(
            select(Payment).where(Payment.user_id == user.id).order_by(Payment.paid_at.desc())
        )
    if payment is None:
        raise RuntimeError("чек не из чего собрать: оплаты нет")

    subscription = user.active_subscription()
    expires = subscription.expires_at if subscription else payment.paid_at
    period_days = subscription.period_days if subscription else 30

    return letters.receipt(
        login=user.login,
        amount=payment.amount,
        currency=payment.currency,
        period_days=period_days,
        paid_at=payment.paid_at,
        expires_at=expires,
        method=_method_label(payment.method),
        receipt_no=f"PV-{payment.paid_at:%Y}-{payment.id:06d}",
    )


def _reminder_letter(user: User):
    subscription = user.active_subscription()
    if subscription is None:
        raise RuntimeError("напоминать не о чем: действующей подписки нет")
    left = max(0, (subscription.expires_at - utcnow()).days)
    return letters.renewal_reminder(
        login=user.login,
        amount=subscription.price,
        currency=subscription.currency,
        period_days=subscription.period_days,
        expires_at=subscription.expires_at,
        days_left=left,
    )


# Как назвать способ оплаты в чеке. Внутренние коды провайдеров человеку
# ничего не говорят, а «panel» в чеке выглядит как ошибка.
METHODS = {
    "yookassa": "Банковская карта",
    "cryptocloud": "Криптовалюта",
    "mock": "Тестовая оплата",
    "панель": "Вручную",
    "panel": "Вручную",
}


def _method_label(method: str | None) -> str:
    return METHODS.get((method or "").lower(), method or "—")


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
