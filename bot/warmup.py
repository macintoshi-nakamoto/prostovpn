import asyncio
import sys
import time


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from app import BotSession
from config.settings import config
from database import db, models
from utils import assets
from utils.render import media_key


FILES = assets.SCREENS


async def main() -> None:
    await db.init()

    if not config.admin_ids:
        print("ADMIN_IDS пуст — прогревать некуда")
        return

    chat = config.admin_ids[0]
    failed = 0
    bot = Bot(token=config.token, session=BotSession(timeout=600))

    for path in FILES:
        if not path.exists():
            print(f"{path.name}: файла нет, пропускаю")
            continue

        key = media_key(path)

        if await models.get_media(key):
            print(f"{path.name}: уже выгружена")
            continue

        started = time.monotonic()

        try:
            message = await bot.send_animation(chat, FSInputFile(str(path)), caption="прогрев")
        except TelegramAPIError as error:
            print(f"{path.name}: не вышло за {time.monotonic() - started:.0f}с — {error}")
            failed += 1
            continue

        spent = time.monotonic() - started

        if message.animation:
            await models.save_media(key, message.animation.file_id)
            size = path.stat().st_size / 1024 / 1024
            print(f"{path.name}: выгружена, {size:.1f} МБ за {spent:.1f}с")

        await bot.delete_message(chat, message.message_id)

    await bot.session.close()

    if failed:
        print(f"прогрев закончен, не вышло файлов: {failed} — повторите запуск позже")
    else:
        print("прогрев закончен")


if __name__ == "__main__":
    asyncio.run(main())
