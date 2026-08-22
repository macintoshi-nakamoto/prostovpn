"""Общий визуальный слой: цвета кнопок и премиум-эмодзи.

Цвет — только у важных кнопок: оплата и продление, выход, назад. Остальные
серые, иначе экран превращается в светофор.

Telegram принимает только четыре стиля, остальные значения отклоняются с
ошибкой "invalid button style specified".
"""

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CopyTextButton, InlineKeyboardButton


PRIMARY = "primary"    # синяя  — оставлена для точечных акцентов
SUCCESS = "success"    # зелёная — оплата, продление, тарифы
DANGER = "danger"      # красная — назад, отмена, выход
DEFAULT = "default"    # серая  — всё остальное


# Наш набор: https://t.me/addemoji/ProstoVPNcc
#
# Пара «слот — эмодзи» подобрана по смыслу, а не по красоте: глобус у
# бренда (это VPN), ключ у входа, купюра у тарифов, кошелёк у оплаты.
# Одинаковые действия во всех экранах помечены одним и тем же значком —
# иначе человек перестаёт читать значки вовсе.
EMOJI_IDS = {
    "brand": "5197367124917530388",     # 🌍  сервис
    "profile": "5197525592030881342",   # 🤵  личный кабинет
    "wallet": "5199782760553686218",    # 💰  оплата
    "balance": "5197714935664127506",   # ⭐️  звёзды Telegram
    "support": "5197395368622464947",   # 🤗  поддержка
    "channel": "5197493409840933457",   # 🐦  канал
    "back": "5197380971892089009",      # ⚫️  назад (нейтральная точка)
    "cross": "5197293230005201451",     # 💤  выход и отмена
    "check": "5197298396850856805",     # 👍  готово
    "rocket": "5199519951504846761",    # 🔥  о сервисе, установка
    "link": "5199528099057807041",      # 📁  документы и ссылки
    "key": "5197603236449655862",       # 🔑  пароль и ключи
    "history": "5197601849175224737",   # 🎟  платежи
    "calendar": "5197187260277109252",  # 💵  тарифы и сроки
    "empty": "5197635822366533157",     # 🥲  пусто
    "warn": "5197627408525601080",      # 😱  что-то пошло не так
    "friends": "5199593906546715997",   # 👊  друзья и приглашения
    "gift": "5197205775881118398",      # 🧸  подарочные дни
    "star": "5197189291796637000",      # ✨  акцент в тексте
}

# Базовый символ пары: он и подставляется, если премиум-эмодзи не прошли.
EMOJI_FALLBACK = {
    "brand": "🌍",
    "profile": "🤵",
    "wallet": "💰",
    "balance": "⭐️",
    "support": "🤗",
    "channel": "🐦",
    "back": "⚫️",
    "cross": "💤",
    "check": "👍",
    "rocket": "🔥",
    "link": "📁",
    "key": "🔑",
    "history": "🎟",
    "calendar": "💵",
    "empty": "🥲",
    "warn": "😱",
    "friends": "👊",
    "gift": "🧸",
    "star": "✨",
}


_custom_emoji = True


def custom_emoji_enabled() -> bool:
    return _custom_emoji


def disable_custom_emoji() -> None:
    """Отключает премиум-эмодзи, если Telegram их не пропустил."""
    global _custom_emoji
    _custom_emoji = False


def premium_rejected(error: TelegramBadRequest) -> bool:
    """Telegram отклонил премиум-эмодзи в тексте или иконку на кнопке."""
    description = str(error).lower()

    return "emoji" in description or "icon" in description


def tg(name: str, fallback: str | None = None) -> str:
    symbol = fallback or EMOJI_FALLBACK[name]

    if not _custom_emoji:
        return symbol

    return f'<tg-emoji emoji-id="{EMOJI_IDS[name]}">{symbol}</tg-emoji>'


def make_btn(
    text: str,
    *,
    url: str | None = None,
    callback_data: str | None = None,
    emoji: str | None = None,
    style: str | None = DEFAULT,
    copy_text: str | None = None,
) -> InlineKeyboardButton:
    kwargs = {}

    if url:
        kwargs["url"] = url
    if callback_data:
        kwargs["callback_data"] = callback_data
    if copy_text:
        kwargs["copy_text"] = CopyTextButton(text=copy_text)
    if emoji and _custom_emoji:
        kwargs["icon_custom_emoji_id"] = EMOJI_IDS[emoji]
    if style:
        kwargs["style"] = style

    return InlineKeyboardButton(text=text, **kwargs)
