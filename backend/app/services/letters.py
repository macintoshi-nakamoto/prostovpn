"""
Письма по макетам: чек, напоминание о продлении, подключённая почта.

Отдельно от `mail.py` намеренно. Там — транспорт: как отдать письмо
провайдеру и что делать, когда он не ответил. Здесь — содержимое: что
человек прочитает. Смешивать их значит однажды править вёрстку в модуле,
который отвечает за доставку.

Картинки лежат на нашем же домене и подключаются абсолютными адресами.
Относительные имена в письме не работают вовсе — почтовому клиенту не от
чего их отсчитывать, — а вложения `cid:` половина клиентов показывает
скрепкой рядом с письмом, чего нам не нужно.

Время показываем московское. Сервер живёт в UTC, и «доступ отключится в
15:42» вместо 18:42 — это не мелочь: по такому письму человек считает,
сколько у него осталось.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import settings

TEMPLATES = Path(__file__).resolve().parent.parent / "emails"

# Сдвиг показа. Не `zoneinfo`, потому что база часовых поясов на голом
# Debian-контейнере бывает не установлена, а падать на письме из-за этого
# нельзя. Москва зимой и летом одна и та же — переход на летнее время
# отменён в 2014 году, так что постоянный сдвиг здесь точен.
MSK = dt.timezone(dt.timedelta(hours=3))

MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

# Числительные словами до пяти: «Осталось три дня» читается, «Осталось 3 дня»
# выглядит как счётчик. Дальше пяти в заголовке не нужно — напоминание уходит
# максимум за несколько дней.
WORDS = {1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять"}


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        # Экранирование обязательно: в письмо попадают логин и почта, то есть
        # то, что человек ввёл сам. Без него чужая кавычка ломает вёрстку, а
        # чужой тег — превращает чек в что угодно.
        autoescape=select_autoescape(["html"]),
    )


def _msk(moment: dt.datetime) -> dt.datetime:
    """Момент в московском времени. Наивный считаем за UTC — так его пишет база."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(MSK)


def date_full(moment: dt.datetime) -> str:
    """14 марта 2027"""
    local = _msk(moment)
    return f"{local.day} {MONTHS[local.month - 1]} {local.year}"


def date_short(moment: dt.datetime) -> str:
    """14 марта"""
    local = _msk(moment)
    return f"{local.day} {MONTHS[local.month - 1]}"


def date_time(moment: dt.datetime) -> str:
    """14 марта 2026, 18:42"""
    local = _msk(moment)
    return f"{date_full(moment)}, {local:%H:%M}"


def date_at_time(moment: dt.datetime) -> str:
    """14 марта в 18:42"""
    local = _msk(moment)
    return f"{date_short(moment)} в {local:%H:%M}"


def money(amount: Decimal | float | int, currency: str = "RUB") -> str:
    """
    2 028 ₽

    Разряды разделяем узким неразрывным пробелом: обычный пробел почтовые
    клиенты переносят на другую строку, и сумма разрывается пополам.
    """
    value = Decimal(str(amount))
    whole = int(value)
    text = f"{whole:,}".replace(",", " ")
    if value != whole:
        text += f",{int(round((value - whole) * 100)):02d}"
    sign = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(currency.upper(), currency)
    return f"{text} {sign}"


def period_label(days: int) -> str:
    """«12 месяцев», «30 дней» — то, за что человек заплатил."""
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
    """«Осталось три дня», «Остался один день»."""
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


# --- сами письма --------------------------------------------------------------


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
    """Чек об оплате. Возвращает тему, текст и вёрстку."""
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
    """Напоминание за несколько дней до конца подписки."""
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
    """
    Ссылка на смену пароля.

    В теме и в тексте нет ни адреса, ни намёка на то, чей это ящик: письмо о
    смене пароля читают в спешке и чаще всего на телефоне с превью на
    заблокированном экране.
    """
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
    """Почта привязана к учётке — рассказываем, что теперь сюда приходит."""
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
