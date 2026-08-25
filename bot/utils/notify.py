from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config.settings import config
from utils.logger import logger


async def notify_admins(bot: Bot, text: str) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode=None)
        except TelegramAPIError as error:
            logger.warning("Не удалось уведомить админа %s: %s", admin_id, error)
