"""
Пускает в бота только подписчиков канала.

Стоит на диспетчере, а не на отдельных роутерах: требование общее для всех
входов, и вешать его на каждый роутер значит однажды завести новый и забыть.

Три вещи проезжают мимо проверки, и каждая по своей причине:

* `successful_payment` — деньги уже списаны. Держать оплату заложником
  подписки нельзя ни при каких условиях: подписка не начислится, а вернуть
  звёзды придётся руками;
* сама кнопка «Я подписался» — иначе она упиралась бы в тот же экран,
  который пытается закрыть;
* администраторы — им бот нужен рабочим независимо от того, что у них с
  подпиской.

Пригласительная ссылка запоминается ДО показа экрана. Без этого подарок
терялся бы: `/start promo_КОД` не доходит до своего хендлера, и человек,
подписавшись, оказывался бы на обычном первом экране без всяких дней.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config.settings import config
from database import models
from handlers.common import show_subscribe
from utils.channel import is_subscribed


CONFIRM = "subscribed"


class ChannelMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")

        if user is None or user.id in config.admin_ids:
            return await handler(event, data)

        if isinstance(event, Message) and event.successful_payment:
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and event.data == CONFIRM:
            return await handler(event, data)

        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        bot = data.get("bot")
        if bot is None or await is_subscribed(bot, user.id):
            return await handler(event, data)

        days = await _remember_gift(event, user.id)

        if isinstance(event, CallbackQuery):
            await event.answer()

        await show_subscribe(event, days)

        return None


async def _remember_gift(event: TelegramObject, user_id: int) -> int | None:
    """
    Записывает переход по пригласительной ссылке и возвращает размер подарка.

    Разбор здесь, а не в хендлере промо: до хендлера апдейт не доедет — мы
    его как раз и останавливаем.
    """
    from handlers.promo import remember_from_payload

    if isinstance(event, Message) and (event.text or "").startswith("/start"):
        parts = (event.text or "").split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else None
        promo = await remember_from_payload(user_id, payload)
        if promo is not None:
            return promo.days

    pending = await models.pending_promo(user_id)

    return pending.days if pending else None
