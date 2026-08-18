"""Оплата: подтверждение счёта и продление подписки в панели."""

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from database import models
from handlers.common import show_screen
from keyboards.menus import after_payment_menu, back_menu
from keyboards.ui import tg
from utils import assets, panel, screens, texts
from utils.logger import logger
from utils.notify import notify_admins
from utils.render import show


router = Router()


METHODS = {"stars": "Telegram Stars", "card": "Карта в боте"}


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    code = query.invoice_payload.split(":", maxsplit=1)[0]

    try:
        plan = await panel.plan_by_code(code)
    except panel.PanelError:
        # Панель молчит — деньги не берём: продлить всё равно не сможем.
        await query.answer(ok=False, error_message="Сервис недоступен, попробуйте позже")
        return

    if not plan:
        await query.answer(ok=False, error_message="Тариф больше недоступен")
        return

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    code, _, method = payment.invoice_payload.partition(":")
    user_id = message.from_user.id

    session = await models.get_session(user_id)
    login = session.panel_login if session else await models.last_login(user_id)

    logger.info(
        "оплата: user=%s логин=%s тариф=%s сумма=%s %s",
        user_id,
        login,
        code,
        payment.total_amount,
        payment.currency,
    )

    plan = None

    try:
        plan = await panel.plan_by_code(code)

        if plan is None:
            raise panel.PanelError(f"тариф «{code}» пропал из витрины")

        if not login:
            raise panel.PanelError("не знаем, какой учётке продлевать")

        await panel.extend(login, plan, METHODS.get(method, "Telegram"))
    except panel.PanelError as error:
        logger.error("продление после оплаты не прошло: %s", error)

        await show(
            message,
            lambda: (
                f'{tg("warn")} <b>Оплата получена</b>\n\n'
                "Не удалось включить подписку автоматически — уже разбираемся, "
                "доступ включим вручную.",
                back_menu("support", "Поддержка"),
            ),
        )

        await notify_admins(
            message.bot,
            f"⚠️ Оплата прошла, продление НЕ выполнено\n"
            f"Пользователь: {user_id}\n"
            f"Логин: {login or '—'}\n"
            f"Тариф: {code}\n"
            f"Сумма: {payment.total_amount} {payment.currency}\n"
            f"Платёж: {payment.telegram_payment_charge_id}\n"
            f"Причина: {error}",
        )
        return

    account = None

    if session:
        try:
            account = await panel.account(session.token)
        except panel.PanelError:
            account = None

    await show_screen(
        message,
        lambda file_id: screens.paid(file_id, plan, account),
        after_payment_menu(),
        text=texts.paid_text(plan, account),
        animation=assets.CABINET_ACTIVE,
    )

    await notify_admins(
        message.bot,
        f"💸 Оплата\n"
        f"Логин: {login}\n"
        f"Тариф: {plan.title}\n"
        f"Сумма: {payment.total_amount} {payment.currency}",
    )
