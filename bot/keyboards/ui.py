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


# Набор LedScreenEmoji: https://t.me/addemoji/LedScreenEmoji
EMOJI_IDS = {
    "brand": "5404652296845936873",     # ⚡️
    "profile": "5406885550990841026",   # 👀
    "wallet": "5406929905118106968",    # 🎁
    "balance": "5402435230432775363",   # ⭐️
    "support": "5375313568520490700",   # ⁉️
    "channel": "5375080832832652559",   # ❗️
    "back": "5400169738263352182",      # ◀️
    "cross": "5408869860241329035",     # ⛔️
    "check": "5411081880067922391",     # 👍
    "rocket": "5406769101542543979",    # ✈️
    "link": "5406769101542543979",      # ✈️
    "key": "5370698664815645720",       # 🔡
    "history": "5370763355613057637",   # 🔣
    "calendar": "5370763355613057637",  # 🔣
    "empty": "5397801415986926341",     # 😴
    "warn": "5406954614064958849",      # ☹️
}

# Базовый символ пары: он и подставляется, если премиум-эмодзи не прошли.
EMOJI_FALLBACK = {
    "brand": "⚡️",
    "profile": "👀",
    "wallet": "🎁",
    "balance": "⭐️",
    "support": "⁉️",
    "channel": "❗️",
    "back": "◀️",
    "cross": "⛔️",
    "check": "👍",
    "rocket": "✈️",
    "link": "✈️",
    "key": "🔡",
    "history": "🔣",
    "calendar": "🔣",
    "empty": "😴",
    "warn": "☹️",
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
