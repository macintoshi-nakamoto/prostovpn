from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

import httpx

from ..config import settings
from .errors import PanelError

log = logging.getLogger("panel.telegram")

# initData живёт недолго: Telegram выдаёт свежую при каждом открытии
# мини-приложения, а подписанная строка — это готовый вход без пароля.
# Час — запас на медленные сети и повторный вход после смены пароля;
# старее — считаем украденной.
INIT_DATA_MAX_AGE = 3600


def validate_init_data(init_data: str, token: str) -> dict:
    """
    Проверяет подпись initData мини-приложения и возвращает разобранные поля.

    Алгоритм из документации Telegram: secret = HMAC_SHA256("WebAppData",
    токен бота), подпись — HMAC_SHA256(secret, отсортированные пары
    key=value без поля hash). Не сошлось — данные не от Telegram.
    """
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    if not received:
        raise PanelError("подпись Telegram не найдена", "tg_invalid")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise PanelError("подпись Telegram не сошлась", "tg_invalid")

    auth_date = pairs.get("auth_date", "")
    if not auth_date.isdigit() or time.time() - int(auth_date) > INIT_DATA_MAX_AGE:
        raise PanelError("данные Telegram устарели — откройте приложение заново", "tg_stale")

    try:
        pairs["user"] = json.loads(pairs.get("user", "") or "{}")
    except ValueError:
        pairs["user"] = {}
    return pairs

USERNAME_MAX = 32


def clean_username(value: str | None) -> str | None:
    """
    Приводит @юзернейм к тому виду, в котором он лежит в базе: без «@».

    Юзернейм в Telegram не обязателен и приходит то с решёткой, то без, то
    пустой строкой. Всё, что не похоже на юзернейм, отбрасываем: поле нужно
    только для показа в админке, и мусор там хуже пустоты.
    """
    name = (value or "").strip().lstrip("@")
    if not name or len(name) > USERNAME_MAX:
        return None
    return name if all(c.isascii() and (c.isalnum() or c == "_") for c in name) else None


API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


class TelegramFatal(TelegramError):
    pass


def enabled() -> bool:
    return bool(settings().telegram_bot_token)


def send(chat_id: str | int, text: str) -> None:
    token = settings().telegram_bot_token
    if not token:
        raise TelegramError("PANEL_TELEGRAM_BOT_TOKEN не задан")

    try:
        response = httpx.post(
            f"{API}/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        raise TelegramError(f"Telegram недоступен: {exc}") from exc

    if response.status_code >= 400:
        body = response.text[:200]
        if response.status_code == 403:
            raise TelegramError(f"бот заблокирован или диалог не начат: {body}")
        if response.status_code == 400 and "chat not found" in body.lower():
            raise TelegramFatal(f"чат не найден: {body}")
        raise TelegramError(f"Telegram вернул {response.status_code}: {body}")


def _ios_note(site: str) -> str:
    return (
        "\n\nНа iPhone приложения нет — подключение через AmneziaVPN из App Store. "
        f"Ключ уже готов в личном кабинете: {site}/account\n"
        f"Инструкция: {settings().guide_link}"
    )


def credentials_text(login: str, password: str, expires_at: str, site: str, ios: bool = False) -> str:
    return (
        "Доступ готов.\n\n"
        f"Логин: <code>{login}</code>\n"
        f"Пароль: <code>{password}</code>\n\n"
        f"Действует до {expires_at}.\n"
        f"Приложение: {site}/download.html\n\n"
        "Введите эти две строки в приложении — больше ничего настраивать не нужно."
        + (_ios_note(site) if ios else "")
    )


def renewed_text(login: str, expires_at: str, site: str, ios: bool = False) -> str:
    return (
        f"Подписка продлена до {expires_at}.\n\n"
        f"Логин прежний: <code>{login}</code>. Пароль не менялся — "
        "приложение продолжит работать само."
        + ("\nКлюч для AmneziaVPN тоже прежний." if ios else "")
        + f"\n\nЛичный кабинет: {site}/account"
    )


def recurring_on_text(
    plan_name: str, price_label: str, interval_label: str, next_charge: str, site: str
) -> str:
    next_line = f"Следующее списание — {next_charge}.\n" if next_charge else ""
    return (
        f"Автопродление подключено: «{plan_name}», {price_label} {interval_label}.\n"
        f"{next_line}\n"
        f"Отключить можно в любой момент: {site}/account"
    )


def recurring_failed_text(plan_name: str, price_label: str, expires_at: str, site: str) -> str:
    return (
        f"Не получилось списать оплату за продление — «{plan_name}», {price_label}.\n\n"
        f"Доступ действует до {expires_at}. Чтобы он не прервался, "
        f"продлите подписку вручную: {site}/account"
    )


def days_received_text(days: int, sender: str, expires_at: str, site: str) -> str:
    return (
        f"Вам передали {days} дн. доступа — от аккаунта {sender}.\n\n"
        f"Теперь подписка действует до {expires_at}."
    )


def referral_join_text(days: int, expires_at: str, site: str) -> str:
    return (
        f"По вашей ссылке пришёл друг — плюс {days} дн. доступа.\n\n"
        f"Теперь подписка действует до {expires_at}.\n"
        "Когда он оплатит подписку, добавим ещё дней."
    )


def referral_purchase_text(days: int, expires_at: str, site: str) -> str:
    return (
        f"Ваш друг оплатил подписку — плюс {days} дн. доступа.\n\n"
        f"Теперь подписка действует до {expires_at}. Спасибо!"
    )


def recurring_off_text(plan_name: str, expires_at: str, site: str) -> str:
    return (
        f"Автопродление по тарифу «{plan_name}» отключено — больше ничего "
        f"списываться не будет.\n\n"
        f"Оплаченный доступ действует до {expires_at}."
    )
