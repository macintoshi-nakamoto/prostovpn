"""Разовая рассылка: «Prosto теперь — приложение в Telegram».

Запуск на сервере из каталога бота:

    venv/bin/python broadcast_miniapp.py test   # только админу, посмотреть глазами
    venv/bin/python broadcast_miniapp.py run    # всем из таблицы users

Отправка — тем же путём, что письма вдогонку (drip._send): видео с подписью
и кнопкой, кэш file_id, премиум-эмодзи с фолбэком, вежливые паузы.
"""

import asyncio
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import aiosqlite
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from app import BotSession
from config.settings import config
from database import db
from database.db import DB_PATH
from keyboards.ui import make_btn, tg
from utils import assets
from utils.drip import SEND_PAUSE, _send
from utils.logger import logger


def post_text() -> str:
    return (
        f'{tg("rocket")} <b>Prosto теперь — приложение в Telegram!</b>\n\n'
        "Открыл — и всё под рукой:\n"
        f'{tg("key")} подключение и ключи\n'
        f'{tg("calendar")} тарифы и оплата: СБП, Stars, крипта\n'
        f'{tg("friends")} дни в подарок за друзей\n\n'
        f'{tg("star")} Никаких сайтов и переписок — жмите кнопку, всё уже внутри.'
    )


def post_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Открыть приложение", web_app=f"{config.site_url}/account")],
        ]
    )


async def user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute("SELECT user_id FROM users ORDER BY user_id")
        return [row[0] for row in await cursor.fetchall()]


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"

    if mode not in ("test", "run"):
        print("режимы: test (только админу) или run (всем)")
        return

    await db.init()

    if mode == "test":
        if not config.admin_ids:
            print("ADMIN_IDS пуст — некому показывать")
            return
        targets = [config.admin_ids[0]]
    else:
        targets = await user_ids()

    print(f"получателей: {len(targets)}")
    bot = Bot(token=config.token, session=BotSession(timeout=600))
    sent = failed = 0

    try:
        for i, user_id in enumerate(targets, 1):
            ok = await _send(bot, user_id, assets.MINIAPP, post_text(), post_menu())

            if ok:
                sent += 1
            else:
                failed += 1
                logger.warning("рассылка мини-аппа: %s не получил", user_id)

            if i % 50 == 0:
                print(f"{i}/{len(targets)}: дошло {sent}, мимо {failed}")

            await asyncio.sleep(SEND_PAUSE)
    finally:
        await bot.session.close()

    print(f"готово: дошло {sent}, мимо {failed} из {len(targets)}")


if __name__ == "__main__":
    asyncio.run(main())
