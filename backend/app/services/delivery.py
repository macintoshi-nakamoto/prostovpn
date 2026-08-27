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
    delivered = 0
    for job in pending(db, limit):
        if _deliver(db, job):
            delivered += 1
    return delivered


def _deliver(db: OrmSession, job: DeliveryJob) -> bool:
    job.attempts += 1
    try:
        _send(db, job)
    except telegram.TelegramFatal as exc:
        job.last_error = str(exc)[:500]
        job.attempts = settings().delivery_max_attempts
        db.commit()
        log.warning("доставка %s#%d отменена: %s", job.channel, job.id, exc)
        return False
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
    ios = user.ios_access

    if job.channel == "email":
        letter = _letter(db, job, user)
        if letter is not None:
            subject, text, html = letter
            mail.send(job.target, subject, text, html)
            return

        if job.template == "credentials":
            text, html = mail.credentials_body(user.login, _password(user), expires, ios=ios)
        elif job.template == "recurring_on":
            name, price, interval, next_charge = _recurring_context(db, user)
            text, html = mail.recurring_on_body(name, price, interval, next_charge)
        elif job.template == "recurring_failed":
            name, price, _interval, _next = _recurring_context(db, user)
            text, html = mail.recurring_failed_body(name, price, expires)
        elif job.template == "recurring_off":
            name, _price, _interval, _next = _recurring_context(db, user)
            text, html = mail.recurring_off_body(name, expires)
        elif job.template == "days_received":
            days, sender = _gift_context(job)
            text, html = mail.days_received_body(days, sender, expires)
        else:
            text, html = mail.renewed_body(user.login, expires, ios=ios)
        mail.send(job.target, settings().mail_subject, text, html)
        return

    if job.channel == "telegram":
        if job.template == "credentials":
            body = telegram.credentials_text(user.login, _password(user), expires, site, ios=ios)
        elif job.template == "recurring_on":
            name, price, interval, next_charge = _recurring_context(db, user)
            body = telegram.recurring_on_text(name, price, interval, next_charge, site)
        elif job.template == "recurring_failed":
            name, price, _interval, _next = _recurring_context(db, user)
            body = telegram.recurring_failed_text(name, price, expires, site)
        elif job.template == "recurring_off":
            name, _price, _interval, _next = _recurring_context(db, user)
            body = telegram.recurring_off_text(name, expires, site)
        elif job.template == "days_received":
            days, sender = _gift_context(job)
            body = telegram.days_received_text(days, sender, expires, site)
        elif job.template == "referral_join":
            body = telegram.referral_join_text(_bonus_days(job), expires, site)
        elif job.template == "referral_purchase":
            body = telegram.referral_purchase_text(_bonus_days(job), expires, site)
        else:
            body = telegram.renewed_text(user.login, expires, site, ios=ios)
        telegram.send(job.target, body)
        return

    raise RuntimeError(f"неизвестный канал доставки {job.channel!r}")


REMIND_DAYS_BEFORE = 3


def queue_expiry_reminders(db: OrmSession) -> int:
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
        # У замороженной подписки срок в базе стоит на месте, а часы —
        # тем более: письмо «через три дня всё кончится» человеку на паузе
        # приходило бы каждый раз неправдой. Отметку не ставим — напомним,
        # когда он вернётся.
        if user.is_frozen:
            continue
        address = user.email_plain
        if not address:
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
    if job.template == "receipt":
        return _receipt_letter(db, job, user)
    if job.template == "email_attached":
        return letters.email_attached(email=job.target)
    if job.template == "reminder":
        return _reminder_letter(user)
    if job.template == "password_reset":
        if not job.payload:
            raise RuntimeError("ссылка на смену пароля потеряна")
        site = settings().site_url.rstrip("/")
        return letters.password_reset(
            login=user.login, reset_url=f"{site}/reset?token={job.payload}"
        )
    return None


def _receipt_letter(db: OrmSession, job: DeliveryJob, user: User):
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


METHODS = {
    "yookassa": "Банковская карта",
    "cryptocloud": "Криптовалюта",
    "platega": "СБП",
    "mock": "Тестовая оплата",
    "панель": "Вручную",
    "panel": "Вручную",
}

PAYMENT_METHODS = {
    "sbp": "СБП",
    "crypto": "Криптовалюта",
    "card": "Банковская карта",
    "sberpay": "SberPay",
}


def _method_label(method: str | None) -> str:
    raw = (method or "").strip()
    if not raw:
        return "—"
    provider, separator, inner = raw.partition("·")
    if separator:
        code = inner.strip().lower()
        return PAYMENT_METHODS.get(code, code or provider.strip())
    return METHODS.get(raw.lower(), raw)


def _gift_context(job: DeliveryJob) -> tuple[int, str]:
    raw = (job.payload or "").split(":", maxsplit=1)
    try:
        days = int(raw[0])
    except (ValueError, IndexError):
        days = 0
    sender = raw[1] if len(raw) > 1 else "другого аккаунта"
    return days, sender


def _bonus_days(job: DeliveryJob) -> int:
    try:
        return int(job.payload or 0)
    except ValueError:
        return 0


def _recurring_context(db: OrmSession, user: User) -> tuple[str, str, str, str]:
    from ..models import Plan, RecurringSub
    from .recurring import INTERVAL_LABELS

    sub = db.scalar(
        select(RecurringSub)
        .where(RecurringSub.user_id == user.id)
        .order_by(RecurringSub.id.desc())
        .limit(1)
    )
    if sub is None:
        raise RuntimeError("запись автосписания не найдена, письмо не собрать")
    plan = db.scalar(select(Plan).where(Plan.code == sub.plan_code))
    name = plan.name if plan else sub.plan_code
    currency = "₽" if sub.currency.upper() == "RUB" else sub.currency
    price = f"{sub.amount_kopecks / 100:.0f} {currency}"
    interval = INTERVAL_LABELS.get(sub.interval, "")
    next_charge = sub.next_charge_at.strftime("%d.%m.%Y") if sub.next_charge_at else ""
    return name, price, interval, next_charge


def _password(user: User) -> str:
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
    job.attempts = 0
    job.next_attempt_at = utcnow()
    job.last_error = None
    db.commit()
    _deliver(db, job)
