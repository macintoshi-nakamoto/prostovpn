"""Оплата: сначала способ, потом тариф. Витрина — та же, что на сайте."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice

from config.settings import config, method_by_code
from handlers.common import show_error, show_screen
from keyboards.menus import payment_methods_menu, plans_menu
from middlewares.auth import AuthMiddleware
from utils import assets, panel, screens, texts
from utils.timeutils import plural_days


router = Router()
router.callback_query.middleware(AuthMiddleware())


@router.callback_query(F.data == "plans")
async def methods(callback: CallbackQuery) -> None:
    await show_screen(
        callback,
        screens.methods,
        payment_methods_menu(),
        text=texts.methods_text(),
        animation=assets.PLANS,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("method:"))
async def plans(callback: CallbackQuery) -> None:
    method = method_by_code(callback.data.removeprefix("method:"))

    if not method:
        await callback.answer("Способ оплаты не найден", show_alert=True)
        return

    if not method.shows_catalog:
        await callback.answer(
            f"{method.title} скоро появится. Пока оплата звёздами — доступ включается сразу.",
            show_alert=True,
        )
        return

    try:
        available = await panel.plans()
    except panel.PanelError as error:
        await show_error(callback, texts.panel_error(error))
        await callback.answer()
        return

    await show_screen(
        callback,
        lambda file_id: screens.plans(file_id, method, available),
        plans_menu(available, method),
        text=texts.plans_text(method, available),
        animation=assets.PLANS,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery) -> None:
    _, method_code, plan_code = callback.data.split(":", maxsplit=2)
    method = method_by_code(method_code)

    if not method:
        await callback.answer("Этот способ оплаты пока недоступен", show_alert=True)
        return

    # Витрина без оплаты: тариф и цену показали, счёт выставить пока нечем.
    # Отвечаем до обращения к панели — человеку важен ответ, а не задержка.
    if method.catalog_only:
        await callback.answer(
            f"{method.title} подключается. Сейчас доступна оплата звёздами Telegram — "
            "доступ включается сразу после оплаты.",
            show_alert=True,
        )
        return

    if not method.ready:
        await callback.answer("Этот способ оплаты пока недоступен", show_alert=True)
        return

    try:
        plan = await panel.plan_by_code(plan_code)
    except panel.PanelError as error:
        await show_error(callback, texts.panel_error(error))
        await callback.answer()
        return

    if not plan:
        await callback.answer("Тариф больше недоступен", show_alert=True)
        return

    title = f"{config.brand} — {plan.title}"
    description = f"Подписка на {plural_days(plan.duration_days)}. Дни прибавятся к текущим."

    if method.code == "card":
        await callback.message.answer_invoice(
            title=title,
            description=description,
            payload=f"{plan.code}:card",
            provider_token=config.provider_token,
            currency=config.currency,
            prices=[LabeledPrice(label=plan.title, amount=plan.price_kopecks)],
        )
    else:
        await callback.message.answer_invoice(
            title=title,
            description=description,
            payload=f"{plan.code}:stars",
            currency="XTR",
            prices=[LabeledPrice(label=plan.title, amount=plan.stars)],
        )

    await callback.answer()
