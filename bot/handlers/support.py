from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config.settings import topic_by_code
from database import models
from keyboards.menus import (
    back_menu,
    cancel_menu,
    support_menu,
    ticket_created_menu,
    topic_menu,
)
from handlers.common import show_screen
from middlewares.auth import AuthMiddleware
from states.forms import Support
from utils import assets, screens, texts
from utils.notify import notify_admins
from utils.render import show


router = Router()
router.callback_query.middleware(AuthMiddleware())
router.message.middleware(AuthMiddleware())


OTHER_TOPIC = "Свой вопрос"


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    await show_screen(
        callback,
        screens.support,
        support_menu(),
        text=texts.support_text(),
        animation=assets.SUPPORT,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("faq:"))
async def faq(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    topic = topic_by_code(callback.data.removeprefix("faq:"))

    if not topic:
        await callback.answer("Раздел не найден", show_alert=True)
        return

    await show_screen(
        callback,
        lambda file_id: screens.topic(file_id, topic),
        topic_menu(topic.code),
        text=texts.topic_text(topic),
        animation=assets.SUPPORT,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ticket:"))
async def ticket_start(callback: CallbackQuery, state: FSMContext) -> None:
    topic = topic_by_code(callback.data.removeprefix("ticket:"))

    await state.set_state(Support.message)
    await state.update_data(topic=topic.title if topic else OTHER_TOPIC)

    await show(
        callback,
        lambda: (texts.ticket_prompt_text(topic), cancel_menu("support")),
        animation=assets.SUPPORT,
    )
    await callback.answer()


@router.message(Support.message)
async def ticket_text(message: Message, state: FSMContext) -> None:
    text = (message.text or message.caption or "").strip()

    if not text:
        await message.answer("Опишите проблему текстом.")
        return

    data = await state.get_data()
    topic = data.get("topic", OTHER_TOPIC)

    session = await models.get_session(message.from_user.id)
    login = session.panel_login if session else None

    ticket_id = await models.add_ticket(message.from_user.id, login, topic, text)
    await state.clear()

    await show(
        message,
        lambda: (texts.ticket_created_text(ticket_id), ticket_created_menu()),
        animation=assets.SUPPORT,
    )

    username = message.from_user.username

    await notify_admins(
        message.bot,
        f"🛟 Обращение №{ticket_id}\n"
        f"Пользователь: {'@' + username if username else message.from_user.id}\n"
        f"Логин: {login or '—'}\n"
        f"Тема: {topic}\n\n"
        f"{text}\n\n"
        f"Ответить: /reply {ticket_id} текст",
    )


@router.callback_query(F.data == "tickets")
async def tickets(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    items = await models.last_tickets(callback.from_user.id)

    await show_screen(
        callback,
        lambda file_id: screens.tickets(file_id, items),
        back_menu("support", "Назад"),
        text=texts.tickets_text(items),
        animation=assets.SUPPORT,
    )
    await callback.answer()
