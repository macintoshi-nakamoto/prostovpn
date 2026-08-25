from __future__ import annotations

import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config.settings import config
from utils.logger import logger


JOINED = {"creator", "administrator", "member", "restricted"}

TTL = 6 * 60 * 60

_cache: dict[int, tuple[float, bool]] = {}


def channel_id() -> str:
    return "@" + config.channel_url.rstrip("/").split("/")[-1]


def forget(user_id: int) -> None:
    _cache.pop(user_id, None)


async def is_subscribed(bot: Bot, user_id: int) -> bool:
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
