"""Команды для администраторов: ответ на обращение и быстрая сводка."""

from html import escape

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from config.settings import config
from database import models
from utils.logger import logger


router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids


@router.message(Command("reply"))
async def reply_ticket(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return

    args = (command.args or "").strip()
    ticket_part, _, answer = args.partition(" ")

    if not ticket_part.isdigit() or not answer.strip():
        await message.answer("Формат: <code>/reply НОМЕР текст ответа</code>")
        return

    ticket = await models.get_ticket(int(ticket_part))

    if not ticket:
        await message.answer(f"Обращение №{ticket_part} не найдено.")
        return

    answer = answer.strip()

    try:
        await message.bot.send_message(
            ticket.user_id,
            f"💬 <b>Ответ поддержки по обращению №{ticket.id}</b>\n\n{escape(answer)}",
        )
    except TelegramAPIError as error:
        logger.warning("Не удалось отправить ответ пользователю: %s", error)
        await message.answer("Пользователь недоступен — сообщение не доставлено.")
        return

    await models.answer_ticket(ticket.id, answer)
    await message.answer(f"Ответ по обращению №{ticket.id} отправлен.")
