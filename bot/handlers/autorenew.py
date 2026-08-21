"""Автопродление: статус, подключение и отключение автосписания.

Бот здесь только витрина: подписку у провайдера создаёт и отменяет панель,
списания подтверждают её вебхуки, и сообщения о продлениях человеку шлёт
тоже панель. Поэтому у бота нет своего состояния - каждый экран начинается
с вопроса панели «как дела у этой учётки».
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from database import models
from handlers.common import show_error, show_screen
from keyboards.menus import autorenew_menu
from middlewares.auth import AuthMiddleware
from utils import assets, panel, screens, texts


router = Router()
router.callback_query.middleware(AuthMiddleware())

# Автосписание у провайдера бывает раз в месяц и раз в год - тарифы других
# сроков продаются только разовыми платежами.
RECURRING_DAYS = (30, 365)


async def _login(user_id: int) -> str | None:
    session = await models.get_session(user_id)

    return session.panel_login if session else await models.last_login(user_id)


async def _options() -> list[panel.Plan]:
    return [plan for plan in await panel.plans() if plan.duration_days in RECURRING_DAYS]


async def _show(callback: CallbackQuery, rec: panel.Recurring | None) -> None:
    try:
        options = [] if rec and rec.live else await _options()
    except panel.PanelError:
        options = []

    await show_screen(
        callback,
        lambda file_id: screens.autorenew(file_id, rec, options),
        autorenew_menu(rec, options),
        text=texts.autorenew_text(rec, options),
        animation=assets.PAYMENTS,
    )


@router.callback_query(F.data == "autorenew")
async def autorenew(callback: CallbackQuery) -> None:
    login = await _login(callback.from_user.id)

    if not login:
        await callback.answer("Сначала войдите в аккаунт", show_alert=True)
        return

    try:
        rec = await panel.recurring_state(login)
    except panel.PanelError as error:
        await show_error(callback, texts.panel_error(error), "cabinet")
        await callback.answer()
        return

    await _show(callback, rec)
    await callback.answer()


@router.callback_query(F.data.startswith("rec:on:"))
async def connect(callback: CallbackQuery) -> None:
    login = await _login(callback.from_user.id)

    if not login:
        await callback.answer("Сначала войдите в аккаунт", show_alert=True)
        return

    plan_code = callback.data.removeprefix("rec:on:")

    try:
        rec = await panel.recurring_create(login, plan_code)
    except panel.PanelError as error:
        # Алертом, а не новым экраном: человек остаётся на выборе тарифа.
        await callback.answer(texts.panel_error(error), show_alert=True)
        return

    await _show(callback, rec)
    await callback.answer("Осталось привязать счёт")


@router.callback_query(F.data == "rec:off")
async def disconnect(callback: CallbackQuery) -> None:
    login = await _login(callback.from_user.id)

    if not login:
        await callback.answer("Сначала войдите в аккаунт", show_alert=True)
        return

    try:
        rec = await panel.recurring_cancel(login)
    except panel.PanelError as error:
        if error.status == 400 and "не подключено" in str(error):
            # Отключать нечего - показываем актуальное состояние.
            rec = None
        else:
            await callback.answer(texts.panel_error(error), show_alert=True)
            return

    await _show(callback, rec)
    await callback.answer("Автопродление отключено")
