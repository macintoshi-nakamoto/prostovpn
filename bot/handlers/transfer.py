"""
Передача дней другу.

Дни уже оплачены — это не покупка, а передача своего, поэтому спрашиваем
ровно два ответа: кому и сколько. Проверки (хватает ли дней, существует ли
получатель) делает панель: она одна знает срок доступа, и дублировать её
арифметику в боте значит однажды разойтись с ней в цифрах.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import models
from handlers.common import fetch_account, show_cabinet, show_error, show_screen
from keyboards.menus import back_menu, cancel_menu
from middlewares.auth import AuthMiddleware
from states.forms import Transfer
from utils import assets, panel, screens, texts
from utils.logger import logger
from utils.render import show


router = Router()
router.callback_query.middleware(AuthMiddleware())


@router.callback_query(F.data.in_({"cabinet", "home", "cancel", "plans"}), Transfer.recipient)
@router.callback_query(F.data.in_({"cabinet", "home", "cancel", "plans"}), Transfer.days)
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Выход из перевода по любой кнопке возврата.

    Без этого состояние переживало «Отмену»: человек уходил в кабинет, потом
    писал боту что угодно — и следующее же число уходило переводом.
    Обработчик стоит выше остальных: он должен перехватить кнопку раньше,
    чем её увидит обычный маршрут.
    """
    await state.clear()
    await show_cabinet(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "transfer")
async def start(callback: CallbackQuery, state: FSMContext) -> None:
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None

    if not account:
        return

    try:
        history = await panel.transfers(session.panel_login)
    except panel.PanelError:
        # История — приятное дополнение, а не условие перевода.
        history = []

    await state.set_state(Transfer.recipient)
    await show_screen(
        callback,
        lambda file_id: screens.transfer(file_id, account, history),
        cancel_menu("cabinet"),
        text=texts.transfer_text(account, history),
        animation=assets.PAYMENTS,
    )
    await callback.answer()


@router.message(Transfer.recipient, F.text)
async def recipient(message: Message, state: FSMContext) -> None:
    key = (message.text or "").strip()

    if not key or len(key) > 255:
        await show(
            message,
            lambda: (texts.transfer_who_error(), cancel_menu("cabinet")),
        )
        return

    await state.update_data(recipient=key)
    await state.set_state(Transfer.days)
    await show(message, lambda: (texts.transfer_days_prompt(key), cancel_menu("cabinet")))


@router.message(Transfer.days, F.text)
async def days(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()

    # Только ASCII-цифры: «1²» проходит isdigit, но числом не становится.
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= 3650:
        await show(message, lambda: (texts.transfer_days_error(), cancel_menu("cabinet")))
        return

    data = await state.get_data()
    key = data.get("recipient", "")
    session = await models.get_session(message.from_user.id)

    if not session:
        await state.clear()
        await show(message, lambda: (texts.transfer_days_error(), back_menu("cabinet", "Назад")))
        return

    try:
        record = await panel.transfer_days(session.panel_login, key, int(raw))
    except panel.PanelError as error:
        # Отказы панели — это правила («столько дней нет», «нет такого
        # аккаунта»), и человеку нужен именно их текст, а не «ошибка».
        await show(message, lambda: (texts.transfer_failed(error), cancel_menu("cabinet")))
        return

    await state.clear()
    logger.info(
        "перевод дней: %s → %s, %d дн.", session.panel_login, record.counterpart, record.days
    )
    await show(message, lambda: (texts.transfer_done(record), back_menu("cabinet", "Кабинет")))
