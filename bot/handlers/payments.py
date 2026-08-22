"""Оплата: подтверждение счёта и продление подписки в панели."""

import asyncio

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

# Сколько ждём панель, отвечая на pre_checkout. У Telegram на этот ответ
# десять секунд; берём с запасом, чтобы успеть отправить сам ответ.
PRE_CHECKOUT_BUDGET = 6


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    """
    Последняя точка, где отказ ничего не стоит.

    После ok=True деньги списываются, и любая наша неготовность превращается
    в «оплатил и не получил». Поэтому здесь проверяется всё, что можно
    проверить заранее: жив ли тариф, знаем ли кому продлевать и та ли сумма.
    """
    code, _, paid_with = query.invoice_payload.partition(":")

    try:
        # Ответить Telegram нужно за десять секунд, иначе он сам покажет
        # человеку сбой оплаты. Запрос к панели ждёт своих двадцати пяти, и
        # без этой рамки медленная панель молча съедала бы всё окно.
        plan = await asyncio.wait_for(panel.plan_by_code(code), timeout=PRE_CHECKOUT_BUDGET)
    except (panel.PanelError, asyncio.TimeoutError):
        # Панель молчит — деньги не берём: продлить всё равно не сможем.
        await query.answer(ok=False, error_message="Сервис недоступен, попробуйте позже")
        return

    if not plan:
        await query.answer(ok=False, error_message="Тариф больше недоступен")
        return

    # Кому продлевать. Без учётки платёж превращается в ручной разбор с
    # админом — а человеку проще войти сейчас, чем ждать возврата потом.
    user_id = query.from_user.id
    session = await models.get_session(user_id)
    login = session.panel_login if session else await models.last_login(user_id)

    if not login:
        await query.answer(
            ok=False,
            error_message="Сначала войдите в аккаунт в боте — иначе некому продлевать подписку",
        )
        return

    # Счёт живёт в переписке сколько угодно, а цена тарифа может смениться.
    # Оплатить вчерашний счёт по вчерашней цене нельзя: продлевать будем по
    # сегодняшней, и расхождение осело бы в кассе.
    #
    # Сверяем в той же единице, в какой выставляли: звёздный счёт — в
    # звёздах, счёт картой в боте — в копейках. Одна мерка на оба сломала бы
    # оплату картой, у которой сумма на два порядка другая.
    expected = plan.price_kopecks if paid_with == "card" else plan.stars

    if query.total_amount != expected:
        logger.warning(
            "устаревший счёт: user=%s тариф=%s способ=%s в счёте %s, сейчас %s",
            user_id,
            code,
            paid_with or "?",
            query.total_amount,
            expected,
        )
        await query.answer(
            ok=False,
            error_message="Цена тарифа изменилась — откройте тарифы и создайте новый счёт",
        )
        return

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    code, _, method = payment.invoice_payload.partition(":")
    user_id = message.from_user.id

    session = await models.get_session(user_id)
    login = session.panel_login if session else await models.last_login(user_id)
    charge_id = payment.telegram_payment_charge_id

    logger.info(
        "оплата: user=%s логин=%s тариф=%s сумма=%s %s charge=%s",
        user_id,
        login,
        code,
        payment.total_amount,
        payment.currency,
        charge_id,
    )

    # Записываем платёж ДО обращения к панели: если дальше что-то упадёт,
    # строка останется и платёж можно будет найти и довести руками.
    # Заодно это и защита от повтора — Telegram присылает апдейт заново,
    # если бот не успел его подтвердить, и без отметки подписка продлилась
    # бы дважды.
    fresh = await models.claim_star_payment(
        charge_id=charge_id,
        user_id=user_id,
        plan_code=code,
        amount=payment.total_amount,
        currency=payment.currency,
        panel_login=login,
    )

    if not fresh:
        logger.info("платёж %s уже обработан — повтор пропускаем", charge_id)
        return

    plan = None

    try:
        plan = await panel.plan_by_code(code)

        if plan is None:
            raise panel.PanelError(f"тариф «{code}» пропал из витрины")

        if not login:
            raise panel.PanelError("не знаем, какой учётке продлевать")

        # В способе — и чем платили, и сколько: касса считает в рублях, и без
        # этой подписи звёздный платёж не отличить от ручного продления.
        label = METHODS.get(method, "Telegram")
        if method == "stars":
            label = f"{label} · {payment.total_amount}★"

        await panel.extend(login, plan, label, external_id=charge_id)
        await models.finish_star_payment(charge_id, "done")
    # Ловим ЛЮБОЙ сбой, а не только известный нам PanelError. Деньги уже
    # списаны, и с этого момента молчание — худший из возможных ответов:
    # человек не понимает, что произошло, а мы не знаем, что чинить.
    except Exception as error:  # noqa: BLE001 — см. выше
        logger.exception("продление после оплаты не прошло: %s", error)
        await models.finish_star_payment(charge_id, "failed", str(error)[:400])

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
