"""Показ экранов бота.

Экран — функция без аргументов, возвращающая «текст + клавиатуру». Она
собирается заново при повторной попытке: если Telegram не пропустил
премиум-эмодзи, бот отключает их и перерисовывает экран обычными.

Разделы показываются с анимацией, служебные экраны — текстом. Переход между
ними идёт заменой сообщения: подпись под видео нельзя превратить в текст
правкой.

Каждый файл выгружается в Telegram один раз: полученный file_id лежит в базе
и переживает перезапуск. Выгрузка с сервера небыстрая, и повторять её на
каждое нажатие нельзя.
"""

from collections.abc import Callable
from pathlib import Path

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

from database import models
from keyboards import ui
from utils import rich
from utils.logger import logger


Screen = Callable[[], tuple[str, InlineKeyboardMarkup]]


def media_key(path: Path) -> str:
    """Ключ кэша с размером файла: заменили гифку — старый file_id отпадает."""
    size = path.stat().st_size if path.exists() else 0

    return f"{path}:{size}"


async def show(
    event: Message | CallbackQuery,
    build: Screen,
    *,
    animation: Path | None = None,
) -> None:
    for attempt in (0, 1):
        text, markup = build()
        # На повторе премиум-эмодзи уже отключены, но текст мог быть собран
        # раньше — тогда он всё ещё несёт теги, из-за которых Telegram и
        # отказал. Снимаем их с готовой строки, иначе вторая попытка падает
        # ровно там же, где первая.
        if not ui.custom_emoji_enabled():
            text = ui.strip_custom_emoji(text)

        try:
            await _deliver(event, text, markup, animation)
            return
        except TelegramBadRequest as error:
            if attempt == 0 and ui.premium_rejected(error):
                ui.disable_custom_emoji()
                continue

            raise


async def show_rich(
    event: Message | CallbackQuery,
    blocks: list[dict],
    markup: InlineKeyboardMarkup,
) -> bool:
    """Экран из блоков. False — Telegram не принял, зовите текстовый путь."""
    message = event.message if isinstance(event, CallbackQuery) else None
    chat_id = event.from_user.id
    payload = {"blocks": blocks}

    # Блочный экран правится на месте — переход без мигания.
    if message is not None and _is_rich(message):
        try:
            await event.bot(
                rich.EditRichMessage(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    rich_message=payload,
                    reply_markup=markup,
                )
            )
            return True
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).lower():
                return True
        except TelegramAPIError as error:
            logger.info("правка экрана не прошла, шлём заново: %s", error)

    try:
        await event.bot(
            rich.SendRichMessage(chat_id=chat_id, rich_message=payload, reply_markup=markup)
        )
    except TelegramAPIError as error:
        logger.warning("экран блоками не ушёл: %s", error)
        return False

    # Прежний экран убираем, иначе лента задвоится.
    if message is not None:
        try:
            await message.delete()
        except TelegramAPIError:
            pass

    return True


async def _deliver(
    event: Message | CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup,
    animation: Path | None,
) -> None:
    # Раздел без файла анимации показывается обычным текстовым экраном.
    if animation and not animation.exists():
        animation = None

    if isinstance(event, Message):
        await _send(event, text, markup, animation)
        return

    message = event.message

    if message is None:
        await event.bot.send_message(event.from_user.id, text, reply_markup=markup)
        return

    if animation:
        # Подпись правим, только если на экране уже нужная анимация. Другая
        # картинка правкой не заменяется — сообщение придётся пересобрать.
        known = await models.get_media(media_key(animation))

        if message.animation and known and message.animation.file_id == known:
            try:
                await message.edit_caption(caption=text, reply_markup=markup)
                return
            except TelegramBadRequest as error:
                if "message is not modified" in str(error).lower():
                    return
                if ui.premium_rejected(error):
                    raise

        await _replace(message, text, markup, animation)
        return

    if message.animation or message.photo or message.video or _is_rich(message):
        await _replace(message, text, markup, None)
        return

    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            return

        if ui.premium_rejected(error):
            raise

        await _replace(message, text, markup, None)


def _is_rich(message: Message) -> bool:
    """Сообщение из блоков: правкой в текст его не превратить."""
    return "rich_message" in (message.model_extra or {})


async def _replace(
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup,
    animation: Path | None,
) -> None:
    """Меняет экран с картинки на текст и обратно — старое сообщение убираем."""
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    await _send(message, text, markup, animation)


async def _send(
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup,
    animation: Path | None,
) -> None:
    if animation and animation.exists():
        if await _send_animation(message, text, markup, animation):
            return

    await message.answer(text, reply_markup=markup)


async def _send_animation(
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup,
    animation: Path,
) -> bool:
    """Шлёт анимацию: сначала известным file_id, потом файлом. False — не вышло."""
    key = media_key(animation)
    known = await models.get_media(key)
    sources = [known, None] if known else [None]

    for source in sources:
        try:
            sent = await message.answer_animation(
                source or FSInputFile(str(animation)),
                caption=text,
                reply_markup=markup,
            )
        except TelegramBadRequest as error:
            if ui.premium_rejected(error):
                raise

            if source:
                # file_id больше не годится — забываем и пробуем файлом
                logger.warning("file_id для %s протух: %s", animation.name, error)
                await models.forget_media(key)
                continue

            logger.warning("анимация %s не отправилась: %s", animation.name, error)
            return False
        except TelegramAPIError as error:
            # Сеть или сам Telegram подвели (бывает 504 на выгрузке файла):
            # экран важнее картинки, покажем текстом.
            logger.warning("анимация %s не дошла: %s", animation.name, error)
            return False

        if sent.animation:
            await models.save_media(key, sent.animation.file_id)

        return True

    return False
