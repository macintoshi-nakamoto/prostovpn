from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config.settings import config
from database import models
from handlers.common import show_error, show_screen
from keyboards.menus import friends_menu
from middlewares.auth import AuthMiddleware
from utils import assets, panel, screens, texts
from utils.logger import logger


router = Router()
router.callback_query.middleware(AuthMiddleware())

REF_PREFIX = "ref"


def invite_url(telegram_id: int) -> str:
    return f"https://t.me/{config.bot_username}?start={REF_PREFIX}{telegram_id}"


def inviter_from_payload(payload: str | None) -> int | None:
    if not payload or not payload.startswith(REF_PREFIX):
        return None

    tail = payload[len(REF_PREFIX) :].strip()

    return int(tail) if tail.isascii() and tail.isdigit() else None


async def remember_invite(message: Message, inviter_id: int) -> None:
    session = await models.get_session(message.from_user.id)
    login = session.panel_login if session else await models.last_login(message.from_user.id)

    try:
        await panel.referral_invite(inviter_id, message.from_user.id, login)
    except panel.PanelError as error:
        if error.status != 400:
            logger.warning("приглашение не записано: %s", error)
        return

    logger.info("реферал: %s пришёл по ссылке %s", message.from_user.id, inviter_id)
    await message.answer(
        "Вы пришли по приглашению — вашему другу начислены дни доступа. "
        "Заведите аккаунт и пользуйтесь."
    )


@router.callback_query(F.data == "friends")
async def friends(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id

    session = await models.get_session(user_id)
    if session:
        await panel.referral_link_account(user_id, session.panel_login)

    try:
        stats = await panel.referral_stats(user_id)
    except panel.PanelError as error:
        await show_error(callback, texts.panel_error(error))
        await callback.answer()
        return

    url = invite_url(user_id)

    await show_screen(
        callback,
        lambda file_id: screens.friends(file_id, stats, url),
        friends_menu(url),
        text=texts.friends_text(stats, url),
        animation=assets.CABINET_ACTIVE,
    )

    await callback.answer()
