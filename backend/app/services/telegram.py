"""
Отправка доступа в Telegram — третий канал доставки.

Каналов три не от избытка сил: письмо теряется в спаме, страницу успеха
закрывают до того, как успели переписать пароль. Telegram оставляет доступ
в переписке, которую человек не потеряет.

Канал необязательный: юзер оставляет свой id по желанию. Без токена бота
задания просто не создаются.
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings

log = logging.getLogger("panel.telegram")

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    """Сообщение не ушло — задание вернётся в очередь."""


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
            # Человек не начал диалог с ботом. Ретраи бессмысленны: пока он
            # сам не напишет боту, отправить нельзя.
            raise TelegramError(f"бот заблокирован или диалог не начат: {body}")
        raise TelegramError(f"Telegram вернул {response.status_code}: {body}")


def _ios_note(site: str) -> str:
    """
    Приписка для тех, кто пользуется сервисом с iPhone.

    Сам ключ `vpn://` сюда не кладём, как и в письмо: он работает без
    пароля, а сообщение уходит по идентификатору из заказа — его мог
    оставить и не владелец учётки. Ключ показывает кабинет, за которым
    стоит вход.
    """
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
        + f"\n\nЛичный кабинет: {site}/account.html"
    )
