from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import models
from handlers.common import show_gate, show_home, show_screen, show_start
from handlers.friends import inviter_from_payload, remember_invite
from handlers.promo import offer_promo
from handlers.plans import plan_code_from_payload, send_stars_invoice
from keyboards.menus import about_menu, docs_menu
from utils import assets, panel, screens, texts
from utils.logger import logger


router = Router()


@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()

    known = await models.knows_user(message.from_user.id)

    await models.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    inviter_id = inviter_from_payload(command.args)
    if inviter_id and not known:
        await remember_invite(message, inviter_id)

    if await offer_promo(message, command.args):
        return

    if await offer_stars(message, command.args):
        return

    await show_home(message, message.from_user.id)


async def offer_stars(message: Message, payload: str | None) -> bool:
    code = plan_code_from_payload(payload)

    if not code:
        return False

    user_id = message.from_user.id
    session = await models.get_session(user_id)
    login = session.panel_login if session else await models.last_login(user_id)

    if not login:
        await show_gate(message, user_id)
        return True

    try:
        plan = await panel.plan_by_code(code)
    except panel.PanelError as error:
        logger.warning("тариф по ссылке %r не получен: %s", code, error)
        return False

    if plan is None or not plan.purchasable:
        return False

    return await send_stars_invoice(message, plan)


@router.message(Command("menu"))
async def menu_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_home(message, message.from_user.id)


@router.message(Command("myid"))
async def myid_command(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@router.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_home(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "start")
async def start_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_start(callback)
    await callback.answer()


@router.callback_query(F.data == "gate")
async def gate_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    if await models.get_session(callback.from_user.id):
        await show_home(callback, callback.from_user.id)
    else:
        await show_gate(callback, callback.from_user.id)

    await callback.answer()


@router.callback_query(F.data == "docs")
async def docs_callback(callback: CallbackQuery) -> None:
    authorized = await models.get_session(callback.from_user.id) is not None

    await show_screen(
        callback,
        screens.docs,
        docs_menu(authorized),
        text=texts.docs_text(),
    )
    await callback.answer()


@router.callback_query(F.data == "about")
async def about_callback(callback: CallbackQuery) -> None:
    authorized = await models.get_session(callback.from_user.id) is not None

    try:
        apps = await panel.downloads()
    except panel.PanelError:
        apps = []

    await show_screen(
        callback,
        lambda file_id: screens.about(file_id, apps),
        about_menu(authorized, apps),
        text=texts.about_text(),
        animation=assets.ABOUT,
    )
    await callback.answer()
