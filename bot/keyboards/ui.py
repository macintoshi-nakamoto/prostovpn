import re

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CopyTextButton, InlineKeyboardButton


PRIMARY = "primary"
SUCCESS = "success"
DANGER = "danger"
DEFAULT = "default"


EMOJI_IDS = {
    "brand": "5197367124917530388",
    "profile": "5197525592030881342",
    "wallet": "5199782760553686218",
    "balance": "5197714935664127506",
    "support": "5197395368622464947",
    "channel": "5197493409840933457",
    "back": "5197380971892089009",
    "cross": "5197293230005201451",
    "check": "5197298396850856805",
    "rocket": "5199519951504846761",
    "link": "5199528099057807041",
    "key": "5197603236449655862",
    "history": "5197601849175224737",
    "calendar": "5197187260277109252",
    "empty": "5197635822366533157",
    "warn": "5197627408525601080",
    "friends": "5199593906546715997",
    "gift": "5197205775881118398",
    "star": "5197189291796637000",
    "guide": "5199809999236279190",
    "unlock": "5199428833773661564",
    "ask": "5197567064235090434",
    "crypto": "5199778641680061454",
    "ticket": "5197601849175224737",
    "coffee": "5199858403517703658",
    "best": "5199428700629673304",
    "season": "5199745944094023728",
    "transfer": "5197344133957591848",
    "windows": "5197349902098670049",
    "android": "5199799652660062302",
    "macos": "5197235458400103214",
    "ios": "5199933672819568701",
    "linux": "5199448942810539243",
}

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
    "guide": "🎒",
    "unlock": "🔓",
    "ask": "🙏",
    "crypto": "🤑",
    "ticket": "🎟",
    "coffee": "☕️",
    "best": "💯",
    "season": "💵",
    "transfer": "✊",
    "windows": "🎩",
    "android": "🤖",
    "macos": "🍿",
    "ios": "🐤",
    "linux": "🐸",
}


_custom_emoji = True


def custom_emoji_enabled() -> bool:
    return _custom_emoji


def disable_custom_emoji() -> None:
    global _custom_emoji
    _custom_emoji = False


def premium_rejected(error: TelegramBadRequest) -> bool:
    description = str(error).lower()

    return "emoji" in description or "icon" in description


_TG_EMOJI_RE = re.compile(r"<tg-emoji emoji-id=\"\d+\">(.*?)</tg-emoji>", re.DOTALL)


def strip_custom_emoji(text: str) -> str:
    return _TG_EMOJI_RE.sub(r"\1", text)


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
