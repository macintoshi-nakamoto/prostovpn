"""
Проверка подписки на канал.

Бот — администратор канала, поэтому может спросить у Telegram статус любого
участника. Ответ кэшируется: проверка на КАЖДОЕ нажатие кнопки — это лишний
запрос к Telegram на каждый чих, а отписываются люди редко.

Кэш живёт в памяти и умирает с процессом. Это сознательно: после выкладки
проверка пройдёт заново у всех, и человек, отписавшийся вчера, не проедет по
старой записи.
"""

from __future__ import annotations

import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config.settings import config
from utils.logger import logger


# Статусы, при которых человек считается подписанным. `left` и `kicked` —
# нет; `restricted` тоже пропускаем: он в канале, просто ограничен в правах.
JOINED = {"creator", "administrator", "member", "restricted"}

# Сколько верим прошлому ответу. Шесть часов: отписка в середине этого срока
# ничего не ломает — доступ к VPN она не даёт, а только пускает в меню.
TTL = 6 * 60 * 60

_cache: dict[int, tuple[float, bool]] = {}


def channel_id() -> str:
    """`@имя` канала из ссылки в настройках."""
    return "@" + config.channel_url.rstrip("/").split("/")[-1]


def forget(user_id: int) -> None:
    """Сбрасывает кэш — после нажатия «я подписался» спрашиваем заново."""
    _cache.pop(user_id, None)


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """
    Подписан ли человек на канал.

    Ошибку Telegram считаем подпиской, а не отказом: канал переименовали, бота
    разжаловали, сеть моргнула — во всех этих случаях запирать вход в бота
    хуже, чем пропустить лишнего. Проверка нужна для роста канала, а не для
    безопасности.
    """
    now = time.monotonic()
    hit = _cache.get(user_id)

    if hit is not None and now - hit[0] < TTL:
        return hit[1]

    try:
        member = await bot.get_chat_member(channel_id(), user_id)
        ok = member.status in JOINED
    except TelegramAPIError as error:
        logger.warning("подписку %s проверить не вышло: %s", user_id, error)
        return True

    _cache[user_id] = (now, ok)

    return ok
