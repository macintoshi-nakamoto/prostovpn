"""Оплата: сначала способ, потом тариф. Витрина — та же, что на сайте."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message

from config.settings import config, method_by_code
from database import models
from handlers.common import show_error, show_screen
from database import models
from keyboards.menus import cancel_menu, pay_link_menu, payment_methods_menu, plans_menu
from middlewares.auth import AuthMiddleware
from states.forms import BuyDaily
from utils import assets, panel, screens, texts
from utils.render import show
from utils.timeutils import plural_days


router = Router()
router.callback_query.middleware(AuthMiddleware())

# Способы, которые платятся ссылкой на форму провайдера: счёт выставляет
# панель, бот только показывает кнопку. Остальные (звёзды, карта Telegram)
# выставляют инвойс средствами самого Telegram и идут другой веткой.
LINK_METHODS = frozenset({"sbp", "crypto"})


@router.callback_query(F.data.in_({"plans", "home", "cabinet", "cancel"}), BuyDaily.days)
async def cancel_daily(callback: CallbackQuery, state: FSMContext) -> None:
    """Выход из выбора числа дней: иначе следующее число купит доступ."""
    await state.clear()
    await methods(callback)


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
async def buy(callback: CallbackQuery, state: FSMContext) -> None:
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

    # Посуточный берут пачкой дней: сначала спрашиваем сколько, потом счёт.
    if plan.duration_days == 1 and method.code in LINK_METHODS:
        await state.set_state(BuyDaily.days)
        # Способ запоминаем вместе с тарифом: счёт выставится после ответа
        # про количество дней, и к тому моменту выбор кнопки уже не виден.
        await state.update_data(plan=plan.code, method=method.code)
        await callback.message.answer(texts.daily_prompt(plan))
        await callback.answer()
        return

    if method.code in LINK_METHODS:
        # Оплата по ссылке: счёт выставляет панель у провайдера, бот
        # показывает кнопку. Оплату подтвердит вебхук - и панель напишет
        # сюда же о продлении, самому боту проверять нечего.
        session = await models.get_session(callback.from_user.id)
        login = session.panel_login if session else await models.last_login(callback.from_user.id)

        if not login:
            await callback.answer("Сначала войдите в аккаунт", show_alert=True)
            return

        try:
            link = await panel.payment_link(login, plan, method=method.code)
        except panel.PanelError as error:
            await show_error(callback, texts.panel_error(error))
            await callback.answer()
            return

        await show_screen(
            callback,
            lambda file_id: screens.invoice(file_id, plan, method=method.code),
            pay_link_menu(link.url),
            text=texts.invoice_text(plan, method=method.code),
            animation=assets.PLANS,
        )

        await callback.answer()
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


# Только текст. Без этого фильтра хендлер ловит ЛЮБОЕ сообщение в состоянии
# «сколько дней» — включая служебное successful_payment. Роутер plans
# подключён раньше payments, поэтому подтверждение оплаты звёздами он
# перехватывал первым: деньги списаны, а подписка не продлена.
@router.message(BuyDaily.days, F.text)
async def daily_days(message: Message, state: FSMContext) -> None:
    """Сколько дней берём на посуточном тарифе."""
    raw = (message.text or "").strip()

    # Только ASCII-цифры: «7²» проходит isdigit, но числом не становится.
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= 90:
        await show(message, lambda: (texts.daily_error(), cancel_menu("plans")))
        return

    data = await state.get_data()
    session = await models.get_session(message.from_user.id)
    login = session.panel_login if session else await models.last_login(message.from_user.id)

    if not login:
        await state.clear()
        await show(message, lambda: (texts.daily_error(), cancel_menu("plans")))
        return

    try:
        plan = await panel.plan_by_code(data.get("plan", ""))

        if plan is None:
            raise panel.PanelError("тариф больше недоступен")

        link = await panel.payment_link(
            login, plan, quantity=int(raw), method=data.get("method")
        )
    except panel.PanelError as error:
        await show(message, lambda: (texts.panel_error(error), cancel_menu("plans")))
        return

    await state.clear()
    await show_screen(
        message,
        lambda file_id: screens.invoice(
            file_id, plan, quantity=int(raw), method=data.get("method")
        ),
        pay_link_menu(link.url),
        text=texts.invoice_text(plan, quantity=int(raw), method=data.get("method")),
        animation=assets.PLANS,
    )
