from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from database import models
from handlers.common import fetch_account, show_cabinet, show_error, show_screen
from keyboards.menus import back_menu
from middlewares.auth import AuthMiddleware
from utils import assets, panel, render, screens, texts
from utils.logger import logger


router = Router()
router.callback_query.middleware(AuthMiddleware())

IOS_KEYS_LIMIT = 6


@router.callback_query(F.data == "cabinet")
async def cabinet(callback: CallbackQuery) -> None:
    await show_cabinet(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "history")
async def history(callback: CallbackQuery) -> None:
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None

    if not account:
        return

    await show_screen(
        callback,
        lambda file_id: screens.history(file_id, account.payments),
        back_menu("cabinet", "Назад"),
        text=texts.history_text(account.payments),
        animation=assets.PAYMENTS,
    )

    await callback.answer()


@router.callback_query(F.data == "tunnel")
async def tunnel(callback: CallbackQuery) -> None:
    try:
        file = await panel.tunnel_file()
    except panel.PanelError as error:
        await show_error(callback, texts.panel_error(error), "cabinet")
        await callback.answer()
        return

    await render.show(callback, lambda: (texts.tunnel_text(file), back_menu("cabinet", "Назад")))

    if file is None:
        await callback.answer()
        return

    try:
        content = await panel.tunnel_file_bytes(file.url)
    except panel.PanelError as error:
        logger.warning("файл списка не отправлен: %s", error)
        await callback.answer("Файл сейчас недоступен, попробуйте позже", show_alert=True)
        return

    await callback.message.answer_document(
        BufferedInputFile(content, filename=file.filename),
        caption="Только для iPhone: откройте файл в приложении — сайты добавятся сами.",
    )
    await callback.answer()


@router.callback_query(F.data == "ioskey")
async def ios_key(callback: CallbackQuery) -> None:
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None

    if not account:
        return

    await render.show(
        callback, lambda: (texts.ios_keys_text(account), back_menu("cabinet", "Назад"))
    )

    for key in account.ios_keys[:IOS_KEYS_LIMIT]:
        await callback.message.answer(texts.ios_key_text(key))

    await callback.answer()
