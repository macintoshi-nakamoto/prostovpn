from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from database import models
from handlers.common import show_home
from handlers.promo import show_offer
from utils import channel, texts
from utils.logger import logger


router = Router()


@router.callback_query(F.data == "subscribed")
async def subscribed(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id

    channel.forget(user_id)

    if not await channel.is_subscribed(callback.bot, user_id):
        await callback.answer(texts.subscribe_missing_text(), show_alert=True)
        return

    logger.info("подписка на канал подтверждена: %s", user_id)
    await callback.answer("Подписка есть, спасибо")
    await state.clear()

    promo = await models.pending_promo(user_id)

    if promo is not None:
        await show_offer(callback, promo)
        return

    await show_home(callback, user_id)
