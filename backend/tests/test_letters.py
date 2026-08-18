"""
Письма по макетам.

Проверяем то, что ломается тихо. Незаменённая переменная в чеке не роняет
отправку — человек просто получает письмо с «{{ amount }}» вместо суммы.
Относительный адрес картинки не роняет ничего — картинки просто нет.
Неэкранированный логин не роняет ничего — пока кто-нибудь не заведёт логин
с угловой скобкой.

Запуск: .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

from app.services import letters

PAID = dt.datetime(2026, 3, 14, 15, 42)      # UTC; в Москве это 18:42
EXPIRES = dt.datetime(2027, 3, 14, 15, 42)


def _all_letters():
    return {
        "чек": letters.receipt(
            login="prosto_user", amount=2028, currency="RUB", period_days=360,
            paid_at=PAID, expires_at=EXPIRES, method="СБП", receipt_no="PV-2026-031407",
        ),
        "напоминание": letters.renewal_reminder(
            login="prosto_user", amount=2028, currency="RUB", period_days=360,
            expires_at=EXPIRES, days_left=3,
        ),
        "почта": letters.email_attached(email="user@example.com"),
    }


# --- форматирование -----------------------------------------------------------


def test_moscow_time_not_utc():
    """
    Время показываем московское.

    Сервер живёт в UTC, и «доступ отключится в 15:42» вместо 18:42 — это не
    мелочь: по такому письму человек считает, сколько у него осталось.
    """
    assert letters.date_time(PAID) == "14 марта 2026, 18:42"
    assert letters.date_at_time(EXPIRES) == "14 марта в 18:42"
    assert letters.date_full(EXPIRES) == "14 марта 2027"
    assert letters.date_short(EXPIRES) == "14 марта"


def test_money_keeps_the_sum_on_one_line():
    # Разряды разделены УЗКИМ НЕРАЗРЫВНЫМ пробелом (U+202F), а не обычным:
    # обычный почтовые клиенты переносят на другую строку, и сумма в чеке
    # разрывается пополам. В исходнике эти два пробела на вид одинаковы,
    # поэтому сравниваем с тем, что вернула сама функция, а не с литералом.
    nbsp = " "
    assert letters.money(2028) == f"2{nbsp}028{nbsp}₽"
    assert letters.money(349) == f"349{nbsp}₽"
    assert letters.money(1990.5) == f"1{nbsp}990,50{nbsp}₽"
    assert letters.money(10, "USD") == f"10{nbsp}$"
    assert " " not in letters.money(2028), "разряды разделены обычным пробелом"


@pytest.mark.parametrize(
    "days, expected",
    [(30, "1 месяц"), (60, "2 месяца"), (360, "12 месяцев"), (1, "1 день"), (3, "3 дня"), (7, "7 дней")],
)
def test_period_label(days, expected):
    assert letters.period_label(days) == expected


@pytest.mark.parametrize(
    "days, expected",
    [(1, "Остался один день"), (2, "Осталось два дня"), (3, "Осталось три дня"),
     (5, "Осталось пять дней"), (0, "Подписка заканчивается сегодня")],
)
def test_days_left_title(days, expected):
    assert letters.days_left_title(days) == expected


# --- сама вёрстка -------------------------------------------------------------


def test_no_placeholder_survives():
    """Незаменённая переменная = письмо с «{{ amount }}» вместо суммы."""
    for name, (subject, text, html) in _all_letters().items():
        assert "{{" not in html, f"{name}: в вёрстке осталась переменная"
        assert "{{" not in text, f"{name}: в тексте осталась переменная"
        assert "{{" not in subject, f"{name}: в теме осталась переменная"


def test_images_are_absolute():
    """
    Относительное имя картинки в письме не покажет ничего: почтовому клиенту
    не от чего его отсчитывать.
    """
    for name, (_, _, html) in _all_letters().items():
        for src in re.findall(r'(?:src|background)="([^"]+\.png)"', html):
            assert src.startswith("http"), f"{name}: относительный адрес {src}"
        assert "url('http" in html or "url(" not in html, f"{name}: фон по относительному адресу"


def test_no_foreign_domain_left():
    """В макетах ссылки вели на prostovpn.app — такого домена у нас нет."""
    for name, (_, text, html) in _all_letters().items():
        assert "prostovpn.app" not in html, f"{name}: остался чужой домен в вёрстке"
        assert "prostovpn.app" not in text, f"{name}: остался чужой домен в тексте"


def test_every_letter_has_text_part():
    """
    Текстовая часть обязательна.

    Письмо без неё почтовые фильтры считают подозрительным, а человек с
    отключёнными картинками и строгим клиентом видит пустоту.
    """
    for name, (subject, text, html) in _all_letters().items():
        assert subject.strip(), f"{name}: пустая тема"
        assert len(text.strip()) > 80, f"{name}: текстовая часть слишком короткая"
        assert len(html) > 1000, f"{name}: вёрстка подозрительно короткая"


def test_user_data_is_escaped():
    """
    Логин и почта приходят от человека.

    Без экранирования чужая угловая скобка ломает вёрстку, а чужой тег
    превращает чек во что угодно.
    """
    _, _, html = letters.receipt(
        login='<script>alert(1)</script>', amount=100, currency="RUB", period_days=30,
        paid_at=PAID, expires_at=EXPIRES, method="СБП", receipt_no="PV-1",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_receipt_shows_what_was_paid():
    subject, text, html = letters.receipt(
        login="ivan", amount=349, currency="RUB", period_days=30,
        paid_at=PAID, expires_at=EXPIRES, method="Банковская карта", receipt_no="PV-2026-000042",
    )
    assert "349 ₽" in subject
    for needle in ("349 ₽", "PV-2026-000042", "ivan", "Банковская карта", "1 месяц"):
        assert needle in html, f"в чеке нет «{needle}»"
        assert needle in text, f"в текстовой части чека нет «{needle}»"
