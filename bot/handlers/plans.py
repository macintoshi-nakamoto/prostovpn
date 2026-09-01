"""Оплата: сначала способ, потом тариф. Витрина — та же, что на сайте."""

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
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
from utils.panel import Plan
from utils.logger import logger
from utils.render import show
from utils.timeutils import plural_days


router = Router()
router.callback_query.middleware(AuthMiddleware())

# Способы, которые платятся ссылкой на форму провайдера: счёт выставляет
# панель, бот только показывает кнопку. Остальные (звёзды, карта Telegram)
# выставляют инвойс средствами самого Telegram и идут другой веткой.
LINK_METHODS = frozenset({"sbp", "crypto"})

# Способы, где количество дней спрашиваем мы сами: сумму по ним считает
# панель или мы, и она зависит от числа дней.
QUANTITY_METHODS = LINK_METHODS | {"stars"}

# Что сказать, когда Telegram не принял счёт. Молчание в этом месте читается
# как «кнопка сломана»: человек тапает тариф и не видит вообще ничего.
INVOICE_FAILED = "Не удалось выставить счёт — попробуйте ещё раз через минуту"

# Приставка параметра ссылки «купить звёздами»: t.me/бот?start=pay_year.
# Так с сайта доезжает выбранный тариф. Реферальные ссылки начинаются с
# «ref» и с этой приставкой не пересекаются.
PAY_PREFIX = "pay_"


def plan_code_from_payload(payload: str | None) -> str | None:
    """Код тарифа из параметра ссылки. Чужой формат и мусор — None."""
    if not payload or not payload.startswith(PAY_PREFIX):
        return None

    code = payload[len(PAY_PREFIX) :].strip()
    # Коды тарифов — короткие латинские слова; всё остальное пришло руками.
    if not code or len(code) > 32 or not code.replace("-", "").replace("_", "").isalnum():
        return None

    return code


async def send_stars_invoice(message: Message, plan: Plan, quantity: int = 1) -> bool:
    """
    Счёт в звёздах. Общая точка для бота и для перехода с сайта.

    False — Telegram счёт не принял; звать её должен тот, кто знает, как об
    этом сказать человеку.

    Количество попадает в payload: к приходу оплаты ни экрана, ни состояния
    уже нет, а продлевать надо ровно на столько, за сколько заплатили.
    """
    days = plan.duration_days * quantity
    try:
        await message.answer_invoice(
            title=f"{config.brand} — {plan.title}",
            description=(
                f"Подписка на {plural_days(days)}. Дни прибавятся к текущим."
            ),
            payload=f"{plan.code}:stars:{quantity}",
            currency="XTR",
            # Вводная цена действует на все способы, звёзды не исключение.
            prices=[LabeledPrice(label=plan.title, amount=plan.stars_for(quantity))],
        )
    except TelegramAPIError as error:
        logger.error("счёт звёздами не выставлен (%s): %s", plan.code, error)
        return False

    return True


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
        available = await panel.plans(await models.session_token(callback.from_user.id))
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
        plan = await panel.plan_by_code(
            plan_code, await models.session_token(callback.from_user.id)
        )
    except panel.PanelError as error:
        await show_error(callback, texts.panel_error(error))
        await callback.answer()
        return

    if not plan:
        await callback.answer("Тариф больше недоступен", show_alert=True)
        return

    # Посуточный берут пачкой дней: сначала спрашиваем сколько, потом счёт.
    # Посуточный берут пачкой дней при любом способе, где сумму считаем мы.
    # Раньше звёзды сюда не попадали, и посуточный ими продавался строго по
    # одному дню — при том что экран обещает «сколько нужно».
    if plan.duration_days == 1 and method.code in QUANTITY_METHODS:
        await state.set_state(BuyDaily.days)
        # Способ запоминаем вместе с тарифом: счёт выставится после ответа
        # про количество дней, и к тому моменту выбор кнопки уже не виден.
        await state.update_data(plan=plan.code, method=method.code)
        await callback.message.answer(texts.daily_prompt(plan, method=method.code))
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
        try:
            await callback.message.answer_invoice(
                title=title,
                description=description,
                payload=f"{plan.code}:card",
                provider_token=config.provider_token,
                currency=config.currency,
                prices=[LabeledPrice(label=plan.title, amount=plan.price_kopecks)],
            )
        except TelegramAPIError as error:
            logger.error("счёт картой не выставлен: %s", error)
            await callback.answer(INVOICE_FAILED, show_alert=True)
            return
    elif not await send_stars_invoice(callback.message, plan):
        await callback.answer(INVOICE_FAILED, show_alert=True)
        return

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

    days = int(raw)
    chosen = data.get("method")

    try:
        plan = await panel.plan_by_code(
            data.get("plan", ""), await models.session_token(message.from_user.id)
        )

        if plan is None:
            raise panel.PanelError("тариф больше недоступен")

        # Звёзды платятся счётом Telegram, а не ссылкой на форму провайдера:
        # ветки расходятся здесь, как и на обычном тарифе.
        if chosen == "stars":
            await state.clear()

            if not await send_stars_invoice(message, plan, quantity=days):
                await show(message, lambda: (INVOICE_FAILED, cancel_menu("plans")))

            return

        link = await panel.payment_link(login, plan, quantity=days, method=chosen)
    except panel.PanelError as error:
        await show(message, lambda: (texts.panel_error(error), cancel_menu("plans")))
        return

    await state.clear()
    await show_screen(
        message,
        lambda file_id: screens.invoice(file_id, plan, quantity=days, method=chosen),
        pay_link_menu(link.url),
        text=texts.invoice_text(plan, quantity=days, method=chosen),
        animation=assets.PLANS,
    )
