"""Пускает в разделы бота только тех, кто вошёл в личный кабинет."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from database import models
from handlers.common import show_gate


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")

        if user and await models.get_session(user.id):
            return await handler(event, data)

        if not isinstance(event, (Message, CallbackQuery)) or user is None:
            return None

        if isinstance(event, CallbackQuery):
            await event.answer("Сначала войдите в личный кабинет")

        await show_gate(event, user.id)

        return None
