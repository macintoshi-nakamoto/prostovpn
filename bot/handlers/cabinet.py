from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from database import models
from handlers.common import fetch_account, show_cabinet, show_error, show_screen
from keyboards.menus import (
    back_menu,
    device_confirm_menu,
    devices_menu,
    freeze_confirm_menu,
    ios_menu,
)
from middlewares.auth import AuthMiddleware
from utils import assets, panel, render, screens, texts
from utils.logger import logger


router = Router()
router.callback_query.middleware(AuthMiddleware())

# Сколько ключей шлём за раз. Ссылка `vpn://` — это полторы-две тысячи
# знаков, и одним сообщением их не собрать: у Telegram потолок 4096. При
# нескольких серверах ключей набирается много, а человеку нужны первые —
# остальные всегда видны в кабинете на сайте.
IOS_KEYS_LIMIT = 6


@router.callback_query(F.data == "cabinet")
async def cabinet(callback: CallbackQuery) -> None:
    await show_cabinet(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "history")
async def history(callback: CallbackQuery) -> None:
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None

    if not account:
        return

    await show_screen(
        callback,
        lambda file_id: screens.history(file_id, account.payments),
        back_menu("cabinet", "Назад"),
        text=texts.history_text(account.payments),
        animation=assets.PAYMENTS,
    )

    await callback.answer()


@router.callback_query(F.data == "tunnel")
async def tunnel(callback: CallbackQuery) -> None:
    """
    Файл со списком российских сервисов: отправляем документом, а не ссылкой.

    Ссылку на телефоне открывает браузер — человек видит список доменов
    текстом на экране, и положить его в AmneziaVPN нечем. Файл же система
    предлагает открыть в приложении, а это ровно то, что нужно сделать.
    """
    try:
        file = await panel.tunnel_file()
    except panel.PanelError as error:
        await show_error(callback, texts.panel_error(error), "cabinet")
        await callback.answer()
        return

    await render.show(callback, lambda: (texts.tunnel_text(file), back_menu("cabinet", "Назад")))

    if file is None:
        await callback.answer()
        return

    try:
        content = await panel.tunnel_file_bytes(file.url)
    except panel.PanelError as error:
        logger.warning("файл списка не отправлен: %s", error)
        await callback.answer("Файл сейчас недоступен, попробуйте позже", show_alert=True)
        return

    await callback.message.answer_document(
        BufferedInputFile(content, filename=file.filename),
        caption="Только для iPhone: откройте файл в приложении — сайты добавятся сами.",
    )
    await callback.answer()


@router.callback_query(F.data == "ioskey")
async def ios_key(callback: CallbackQuery) -> None:
    """
    Ключи для AmneziaVPN — по сообщению на устройство.

    Каждый ключ отдельным сообщением с моноширинным блоком: так его
    копируют одним касанием, а собрать несколько ссылок в одно сообщение
    всё равно не выйдет — не хватит длины.
    """
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None

    if not account:
        return

    # Ключа ещё нет, а подписка действует (в том числе пробная) —
    # выпускаем прямо сейчас, а не отправляем «загляните через минуту».
    if not account.ios_keys and account.active:
        try:
            account = await panel.enable_ios(session.token)
        except panel.PanelUnavailable:
            await callback.answer("Панель не отвечает, попробуйте через минуту", show_alert=True)
            return
        except panel.PanelError as error:
            await callback.answer(str(error), show_alert=True)
            return

    await render.show(callback, lambda: (texts.ios_keys_text(account), ios_menu()))

    for key in account.ios_keys[:IOS_KEYS_LIMIT]:
        await callback.message.answer(texts.ios_key_text(key))

    await callback.answer()


@router.callback_query(F.data == "appstore")
async def appstore(callback: CallbackQuery) -> None:
    """Как сменить регион App Store — иначе AmneziaVPN и Happ не поставить."""
    await render.show(callback, lambda: (texts.appstore_text(), back_menu("ioskey", "К ключам")))
    await callback.answer()


# --------------------------------------------------------------------------
# Устройства
# --------------------------------------------------------------------------
#
# Список — всё, что занимает место в лимите тарифа: входы приложения, ключи
# iPhone, ссылки для Happ. Удаление с подтверждением: оно настоящее — пир и
# учётки снимаются с узлов, а не только исчезают из списка.


@router.callback_query(F.data == "devices")
async def devices(callback: CallbackQuery) -> None:
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None
    if not account:
        return
    await render.show(callback, lambda: (texts.devices_text(account), devices_menu(account)))
    await callback.answer()


def _find_device(account, kind: str, device_id: int):
    return next(
        (d for d in account.device_rows if d.kind == kind and d.id == device_id),
        None,
    )


@router.callback_query(F.data.startswith("devdel:"))
async def device_delete_ask(callback: CallbackQuery) -> None:
    _, kind, raw_id = callback.data.split(":", 2)
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None
    if not account:
        return
    device = _find_device(account, kind, int(raw_id))
    if device is None:
        await callback.answer("Этого устройства уже нет", show_alert=True)
        await render.show(callback, lambda: (texts.devices_text(account), devices_menu(account)))
        return
    await render.show(
        callback,
        lambda: (texts.device_confirm_text(device), device_confirm_menu(kind, device.id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("devyes:"))
async def device_delete(callback: CallbackQuery) -> None:
    _, kind, raw_id = callback.data.split(":", 2)
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None
    if not account:
        return
    device = _find_device(account, kind, int(raw_id))
    if device is not None:
        try:
            await panel.delete_device(session.token, device)
        except panel.PanelUnavailable:
            await callback.answer("Панель не отвечает, попробуйте через минуту", show_alert=True)
            return
        except panel.PanelError as error:
            await callback.answer(str(error), show_alert=True)
            return
        logger.info("устройство удалено из бота: %s %s", kind, raw_id)

    account = await fetch_account(callback, session)
    if not account:
        return
    await render.show(callback, lambda: (texts.devices_text(account), devices_menu(account)))
    await callback.answer("Удалено" if device is not None else "Уже удалено")


# --------------------------------------------------------------------------
# Пауза подписки
# --------------------------------------------------------------------------
#
# Заморозка спрашивает подтверждение, разморозка — нет. Разница по цене
# ошибки: случайная пауза выключает человеку интернет, случайная разморозка
# всего лишь запускает дни, которые и так его.


@router.callback_query(F.data == "freeze")
async def freeze_ask(callback: CallbackQuery) -> None:
    """Экран подтверждения. Право на паузу проверяет панель, а не бот."""
    session = await models.get_session(callback.from_user.id)
    account = await fetch_account(callback, session) if session else None

    if not account:
        return

    if account.freeze.frozen:
        await show_cabinet(callback, callback.from_user.id)
        await callback.answer()
        return

    if not account.freeze.can_freeze:
        await render.show(
            callback,
            lambda: (texts.freeze_denied_text(account), back_menu("cabinet", "Назад")),
        )
        await callback.answer()
        return

    await show_screen(
        callback,
        lambda file_id: screens.freeze_ask(file_id, account),
        freeze_confirm_menu(),
        text=texts.freeze_ask_text(account),
        animation=assets.cabinet(account.active),
    )
    await callback.answer()


@router.callback_query(F.data == "freeze:yes")
async def freeze_apply(callback: CallbackQuery) -> None:
    session = await models.get_session(callback.from_user.id)

    if not session:
        return

    try:
        account = await panel.freeze(session.token)
    except panel.PanelError as error:
        # Отказ панели — это её правило, а не поломка: показываем причину и
        # возвращаем в кабинет, а не в пустой экран ошибки.
        logger.info("пауза не поставлена (%s): %s", session.panel_login, error)
        await show_error(callback, texts.panel_error(error), "cabinet")
        await callback.answer()
        return

    logger.info("подписка %s на паузе", session.panel_login)

    await show_screen(
        callback,
        lambda file_id: screens.freeze_done(file_id, account),
        back_menu("cabinet", "В кабинет"),
        text=texts.freeze_done_text(account),
        animation=assets.cabinet(False),
    )
    await callback.answer("Подписка на паузе")


@router.callback_query(F.data == "resume")
async def freeze_resume(callback: CallbackQuery) -> None:
    session = await models.get_session(callback.from_user.id)

    if not session:
        return

    try:
        account = await panel.resume(session.token)
    except panel.PanelError as error:
        logger.warning("пауза не снята (%s): %s", session.panel_login, error)
        await show_error(callback, texts.panel_error(error), "cabinet")
        await callback.answer()
        return

    logger.info("подписка %s снята с паузы", session.panel_login)

    await show_screen(
        callback,
        lambda file_id: screens.resume_done(file_id, account),
        back_menu("cabinet", "В кабинет"),
        text=texts.resume_done_text(account),
        animation=assets.cabinet(True),
    )
    await callback.answer("Доступ вернулся")
