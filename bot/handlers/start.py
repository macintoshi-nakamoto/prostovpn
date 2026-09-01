from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import models
from handlers.common import show_gate, show_start
from handlers.friends import inviter_from_payload, remember_invite
from handlers.promo import offer_promo
from handlers.plans import plan_code_from_payload, send_stars_invoice
from utils import panel
from utils.logger import logger


router = Router()


@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()

    # «Новый» — тот, кто пишет боту впервые: у него ещё нет строки в базе.
    # Проверяем ДО upsert_user, иначе новыми не будет никто.
    known = await models.knows_user(message.from_user.id)

    await models.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    inviter_id = inviter_from_payload(command.args)
    # Приглашение засчитываем только новым: иначе давний клиент, перешедший
    # по ссылке знакомого, дарил бы дни за самого себя.
    if inviter_id and not known:
        await remember_invite(message, inviter_id)

    # Пригласительная ссылка с бесплатным периодом. Раньше приглашения от
    # друга: та отмечает, кто позвал, а эта показывает экран подарка и
    # уводит в регистрацию — два разных смысла и две разные ссылки.
    if await offer_promo(message, command.args):
        return

    # Переход с сайта «оплатить звёздами»: в ссылке приехал тариф. Раньше
    # такая кнопка вела в пустой чат, и выбор, сделанный на сайте, терялся
    # целиком — человеку приходилось искать тариф заново.
    if await offer_stars(message, command.args):
        return

    # Всё в мини-приложении: любой /start показывает экран с кнопкой запуска.
    await show_start(message)


async def offer_stars(message: Message, payload: str | None) -> bool:
    """
    Счёт в звёздах сразу по переходу с сайта. False — обычный первый экран.

    Отказываемся молча (возвращаем False и показываем домашний экран) во всех
    случаях, когда счёт выставить нельзя: неизвестный тариф, тариф не
    продаётся, панель молчит. Человек при этом оказывается в боте, а не в
    сообщении об ошибке, и может дойти до оплаты обычным путём.
    """
    code = plan_code_from_payload(payload)

    if not code:
        return False

    # Без учётки продлевать некому — сначала вход. Тариф при этом не теряется
    # безвозвратно: он остаётся на витрине, и после входа человек выбирает
    # его в два тапа.
    user_id = message.from_user.id
    session = await models.get_session(user_id)
    login = session.panel_login if session else await models.last_login(user_id)

    if not login:
        await show_gate(message, user_id)
        return True

    try:
        plan = await panel.plan_by_code(code, await models.session_token(message.from_user.id))
    except panel.PanelError as error:
        logger.warning("тариф по ссылке %r не получен: %s", code, error)
        return False

    if plan is None or not plan.purchasable:
        return False

    return await send_stars_invoice(message, plan)


@router.message(Command("menu"))
async def menu_command(message: Message, state: FSMContext) -> None:
    """Осталась ради старых закладок: экран тот же, что у /start."""
    await state.clear()
    await show_start(message)


@router.callback_query(F.data == "start")
async def start_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_start(callback)
    await callback.answer()
