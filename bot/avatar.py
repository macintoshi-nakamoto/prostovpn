"""Ставит боту анимированный аватар из assets/avatar.mp4.

Метод setMyProfilePhoto в aiogram ещё не обёрнут, поэтому запрос уходит в
Telegram напрямую: файл прикладывается как attach, а описание — объектом
InputProfilePhoto.

Запуск: venv/bin/python avatar.py
"""

import asyncio
import json
import sys
import time


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import aiohttp

from config.settings import config
from utils import assets


async def main() -> None:
    path = assets.AVATAR

    if not path.exists():
        print(f"нет файла {path}")
        return

    payload = json.dumps(
        {
            "type": "animated",
            "animation": "attach://avatar",
            "main_frame_timestamp": 0.0,
        }
    )

    timeout = aiohttp.ClientTimeout(total=600)
    started = time.monotonic()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        form = aiohttp.FormData()
        form.add_field("photo", payload)

        with path.open("rb") as stream:
            form.add_field("avatar", stream, filename=path.name, content_type="video/mp4")

            async with session.post(
                f"https://api.telegram.org/bot{config.token}/setMyProfilePhoto",
                data=form,
            ) as response:
                answer = await response.json(content_type=None)

    spent = time.monotonic() - started
    size = path.stat().st_size / 1024 / 1024

    if answer.get("ok"):
        print(f"аватар поставлен: {size:.1f} МБ за {spent:.1f}с")
        return

    print(f"не вышло: {answer.get('description')}")


if __name__ == "__main__":
    asyncio.run(main())
