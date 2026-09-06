from __future__ import annotations

import datetime as dt
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import settings

TEMPLATES = Path(__file__).resolve().parent.parent / "emails"

MSK = dt.timezone(dt.timedelta(hours=3))

MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

WORDS = {1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять"}


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )


def _msk(moment: dt.datetime) -> dt.datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(MSK)


def date_full(moment: dt.datetime) -> str:
    local = _msk(moment)
    return f"{local.day} {MONTHS[local.month - 1]} {local.year}"


def date_short(moment: dt.datetime) -> str:
    local = _msk(moment)
    return f"{local.day} {MONTHS[local.month - 1]}"


def date_time(moment: dt.datetime) -> str:
    local = _msk(moment)
    return f"{date_full(moment)}, {local:%H:%M}"


def date_at_time(moment: dt.datetime) -> str:
    local = _msk(moment)
    return f"{date_short(moment)} в {local:%H:%M}"


def money(amount: Decimal | float | int, currency: str = "RUB") -> str:
    value = Decimal(str(amount))
    whole = int(value)
    text = f"{whole:,}".replace(",", " ")
    if value != whole:
        text += f",{int(round((value - whole) * 100)):02d}"
    sign = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(currency.upper(), currency)
    return f"{text} {sign}"


def period_label(days: int) -> str:
    if days >= 30 and days % 30 == 0:
        months = days // 30
        tail = "месяц" if months % 10 == 1 and months % 100 != 11 else (
            "месяца" if 2 <= months % 10 <= 4 and not 12 <= months % 100 <= 14 else "месяцев"
        )
        return f"{months} {tail}"
    tail = "день" if days % 10 == 1 and days % 100 != 11 else (
        "дня" if 2 <= days % 10 <= 4 and not 12 <= days % 100 <= 14 else "дней"
    )
    return f"{days} {tail}"


def days_left_title(days: int) -> str:
    if days <= 0:
        return "Подписка заканчивается сегодня"
    word = WORDS.get(days, str(days))
    if days % 10 == 1 and days % 100 != 11:
        return f"Остался {word} день"
    if 2 <= days % 10 <= 4 and not 12 <= days % 100 <= 14:
        return f"Осталось {word} дня"
    return f"Осталось {word} дней"


def _common() -> dict[str, str]:
    config = settings()
    site = config.site_url.rstrip("/")
    return {
        "img": f"{site}/downloads/email",
        "account_url": f"{site}/account",
        "support_url": config.support_telegram or f"mailto:{config.support_email}",
    }


def _render(name: str, **values: object) -> str:
    return _env().get_template(name).render(**_common(), **values)


def receipt(
    *,
    login: str,
    amount: Decimal | float,
    currency: str,
    period_days: int,
    paid_at: dt.datetime,
    expires_at: dt.datetime,
    method: str,
    receipt_no: str,
) -> tuple[str, str, str]:
    sum_text = money(amount, currency)
    period = period_label(period_days)
    expires = date_full(expires_at)

    subject = f"Чек об оплате — {sum_text}"
    text = (
        f"Оплата прошла: {sum_text}.\n\n"
        f"Чек № {receipt_no}\n"
        f"Дата: {date_time(paid_at)}\n"
        f"Подписка Prosto VPN, {period}\n"
        f"Логин: {login}\n"
        f"Способ оплаты: {method}\n"
        f"Действует до: {expires}\n\n"
        f"Личный кабинет: {_common()['account_url']}\n"
    )
    html = _render(
        "receipt.html",
        login=login,
        amount=sum_text,
        period=period,
        paid_at=date_time(paid_at),
        expires=expires,
        method=method,
        receipt_no=receipt_no,
    )
    return subject, text, html


def renewal_reminder(
    *,
    login: str,
    amount: Decimal | float,
    currency: str,
    period_days: int,
    expires_at: dt.datetime,
    days_left: int,
) -> tuple[str, str, str]:
    sum_text = money(amount, currency)
    period = period_label(period_days)

    subject = f"Подписка заканчивается {date_short(expires_at)}"
    text = (
        f"{days_left_title(days_left)}.\n\n"
        f"Доступ отключится {date_at_time(expires_at)}.\n"
        f"Продлите заранее — подключение не прервётся, ключ и устройства "
        f"останутся те же.\n\n"
        f"Логин: {login}\n"
        f"Тариф: {period}\n"
        f"Продление: {sum_text}\n\n"
        f"Продлить: {_common()['account_url']}\n"
    )
    html = _render(
        "renewal-reminder.html",
        login=login,
        amount=sum_text,
        period=period,
        expires=date_full(expires_at),
        expires_short=date_short(expires_at),
        expires_at=date_at_time(expires_at),
        days_left_title=days_left_title(days_left),
    )
    return subject, text, html


def password_reset(*, login: str, reset_url: str) -> tuple[str, str, str]:
    subject = "Смена пароля — Prosto VPN"
    text = (
        f"Кто-то запросил смену пароля для {login}.\n\n"
        f"Задать новый пароль: {reset_url}\n\n"
        "Ссылка работает 30 минут и только один раз. После смены пароля все "
        "входы в приложениях придётся выполнить заново.\n\n"
        "Если вы этого не просили — просто удалите письмо. Пароль останется "
        "прежним: без этой ссылки сменить его нельзя.\n"
    )
    html = _render("password-reset.html", login=login, reset_url=reset_url)
    return subject, text, html


def email_attached(*, email: str) -> tuple[str, str, str]:
    subject = "Почта подключена — Prosto VPN"
    text = (
        f"Адрес {email} подключён к учётной записи Prosto VPN.\n\n"
        "Сюда будут приходить:\n"
        "— чек об оплате: сумма, дата, срок подписки;\n"
        "— одно напоминание за три дня до продления;\n"
        "— ссылка на смену пароля, если сами попросите.\n\n"
        "Рассылок и рекламы не будет.\n\n"
        f"Личный кабинет: {_common()['account_url']}\n"
    )
    html = _render("email-verified.html", email=email)
    return subject, text, html


def telegram_attached(*, login: str, handle: str) -> tuple[str, str, str]:
    subject = "К учётной записи подключён Telegram — Prosto VPN"
    text = (
        f"К учётной записи {login} подключён Telegram {handle}.\n\n"
        "Теперь с этого Telegram можно входить в кабинет без пароля.\n\n"
        "Если это не вы — смените пароль по ссылке «Забыли пароль» на сайте: "
        "после смены вход по Telegram закроется до входа с новым паролем, "
        "а все входы будут отозваны. Отвязать Telegram можно в личном кабинете.\n\n"
        f"Личный кабинет: {_common()['account_url']}\n"
    )
    html = _render("telegram-attached.html", login=login, handle=handle)
    return subject, text, html
