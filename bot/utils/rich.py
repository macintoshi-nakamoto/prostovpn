"""Кирпичи для экранов на Rich Message.

Telegram собирает такие сообщения из блоков: заголовки, списки, таблицы,
цитаты. Разметка внутри блока задаётся вложенными объектами, а не HTML —
`parse_mode` здесь не работает вовсе.

Схема снята с сообщения, собранного самим редактором Telegram: только у
ячеек таблицы есть выравнивание, поэтому строка по центру — таблица из
одной ячейки.
"""

from typing import Any

from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message

from keyboards.ui import EMOJI_FALLBACK, EMOJI_IDS, custom_emoji_enabled


class SendRichMessage(TelegramMethod[Message]):
    """Метод появился в Bot API 10.1, в aiogram его пока нет."""

    __returning__ = Message
    __api_method__ = "sendRichMessage"

    # Строкой тоже: у каналов адрес вида @name.
    chat_id: int | str
    rich_message: dict[str, Any]
    reply_markup: InlineKeyboardMarkup | None = None


class EditRichMessage(TelegramMethod[Message]):
    """Правка экрана на месте — тот же editMessageText, но блоками."""

    __returning__ = Message
    __api_method__ = "editMessageText"

    chat_id: int | str
    message_id: int
    rich_message: dict[str, Any]
    reply_markup: InlineKeyboardMarkup | None = None


# --------------------------------------------------------------------------
# Кирпичи
# --------------------------------------------------------------------------


def paragraph(text: Any = "") -> dict:
    return {"type": "paragraph", "text": text}


def spacer() -> dict:
    """Пустой абзац — отступ. Так же отбивает пустоту редактор Telegram."""
    return paragraph("")


def bold(text: str) -> dict:
    return {"type": "bold", "text": text}


def italic(text: str) -> dict:
    return {"type": "italic", "text": text}


def code(text: str) -> dict:
    return {"type": "code", "text": text}


def heading(text: str, size: int = 1) -> dict:
    """Размеров ровно три, первый — самый крупный.

    Второй и третий выглядят мельче обычного текста, поэтому заголовки
    разделов идут первым.
    """
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
    """Строка по центру. Выравнивание есть только у ячеек, отсюда таблица."""
    return {"type": "table", "cells": [[{"text": text, "align": "center"}]]}


def emoji(name: str) -> Any:
    """
    Премиум-эмодзи из нашего набора внутри текста блока.

    Кладётся в массив `text` рядом с остальными кусками. Если премиум-эмодзи
    отключены (Telegram их не пропустил), возвращается обычный символ той же
    пары — строка в массиве допустима, и экран не разваливается.
    """
    symbol = EMOJI_FALLBACK[name]

    if not custom_emoji_enabled():
        return symbol

    return {
        "type": "custom_emoji",
        "custom_emoji_id": EMOJI_IDS[name],
        # Именно alternative_text: под этим именем API ждёт запасной символ.
        "alternative_text": symbol,
    }


def title(text: str, icon: str | None = None) -> dict:
    """
    Заголовок раздела: слева, жирным, заглавными.

    Значок перед заголовком — единственное украшение экрана, и он же его
    опознавательный знак: человек узнаёт раздел раньше, чем прочитает
    строку. Два пробела после значка — иначе анимация липнет к букве.
    """
    if icon:
        return paragraph([emoji(icon), bold(f"  {text.upper()}")])

    return paragraph(bold(text.upper()))


def facts(*rows: tuple[str, Any]) -> dict:
    """Таблица «поле — значение»: слева подпись, справа данные."""
    return {
        "type": "table",
        "cells": [[{"text": name}, {"text": value}] for name, value in rows],
    }


def table(header: tuple[str, ...], rows: list[tuple[Any, ...]]) -> dict:
    """Таблица с шапкой. Выравнивание не трогаем — оставляем как по умолчанию."""
    cells = [[{"text": name, "is_header": True} for name in header]]
    cells += [[{"text": value} for value in row] for row in rows]

    return {"type": "table", "cells": cells}


def animation(file_id: str) -> dict:
    return {"type": "animation", "animation": {"type": "animation", "media": file_id}}


def screen(file_id: str | None, *blocks: dict) -> list[dict]:
    """Экран целиком: заставка сверху, отступ снизу перед кнопками."""
    head = [animation(file_id)] if file_id else []

    return [*head, *blocks, spacer()]
