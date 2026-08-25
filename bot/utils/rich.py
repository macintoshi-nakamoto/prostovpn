from typing import Any

from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message

from keyboards.ui import EMOJI_FALLBACK, EMOJI_IDS, custom_emoji_enabled


class SendRichMessage(TelegramMethod[Message]):

    __returning__ = Message
    __api_method__ = "sendRichMessage"

    chat_id: int | str
    rich_message: dict[str, Any]
    reply_markup: InlineKeyboardMarkup | None = None


class EditRichMessage(TelegramMethod[Message]):

    __returning__ = Message
    __api_method__ = "editMessageText"

    chat_id: int | str
    message_id: int
    rich_message: dict[str, Any]
    reply_markup: InlineKeyboardMarkup | None = None


def paragraph(text: Any = "") -> dict:
    return {"type": "paragraph", "text": text}


def spacer() -> dict:
    return paragraph("")


def bold(text: str) -> dict:
    return {"type": "bold", "text": text}


def italic(text: str) -> dict:
    return {"type": "italic", "text": text}


def code(text: str) -> dict:
    return {"type": "code", "text": text}


def heading(text: str, size: int = 1) -> dict:
    return {"type": "heading", "text": text, "size": size}


def bullet(text: Any) -> dict:
    return {"label": "•", "blocks": [paragraph(text)]}


def bullets(*items: Any) -> dict:
    return {"type": "list", "items": [bullet(item) for item in items]}


def numbered(*items: Any) -> dict:
    return {
        "type": "list",
        "items": [
            {"label": f"{number}.", "type": "1", "value": number, "blocks": [paragraph(text)]}
            for number, text in enumerate(items, start=1)
        ],
    }


def quote(*texts: Any) -> dict:
    return {"type": "blockquote", "blocks": [paragraph(text) for text in texts]}


def divider() -> dict:
    return {"type": "divider"}


def centered(text: Any) -> dict:
    return {"type": "table", "cells": [[{"text": text, "align": "center"}]]}


def emoji(name: str) -> Any:
    symbol = EMOJI_FALLBACK[name]

    if not custom_emoji_enabled():
        return symbol

    return {
        "type": "custom_emoji",
        "custom_emoji_id": EMOJI_IDS[name],
        "alternative_text": symbol,
    }


def title(text: str, icon: str | None = None) -> dict:
    if icon:
        return paragraph([emoji(icon), bold(f"  {text.upper()}")])

    return paragraph(bold(text.upper()))


def facts(*rows: tuple[str, Any]) -> dict:
    return {
        "type": "table",
        "cells": [[{"text": name}, {"text": value}] for name, value in rows],
    }


def table(header: tuple[str, ...], rows: list[tuple[Any, ...]]) -> dict:
    cells = [[{"text": name, "is_header": True} for name in header]]
    cells += [[{"text": value} for value in row] for row in rows]

    return {"type": "table", "cells": cells}


def animation(file_id: str) -> dict:
    return {"type": "animation", "animation": {"type": "animation", "media": file_id}}


def screen(file_id: str | None, *blocks: dict) -> list[dict]:
    head = [animation(file_id)] if file_id else []

    return [*head, *blocks, spacer()]
