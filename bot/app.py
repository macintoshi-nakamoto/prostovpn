import asyncio
import os
import socket
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import BotCommand, ErrorEvent

from config.settings import BOT_DESCRIPTION, BOT_SHORT_DESCRIPTION, config
from database.db import init as init_db
from handlers import (
    admin,
    auth,
    cabinet,
    friends,
    payments,
    plans,
    promo,
    start,
    subscribe,
    support,
    transfer,
)
from middlewares.channel import ChannelMiddleware
from utils import drip, panel
from utils.logger import logger


COMMANDS = (
    BotCommand(command="start", description="Открыть приложение"),
)

# Пауза перед новой попыткой, когда Telegram недоступен.
RETRY_PAUSE = 15


class BotSession(AiohttpSession):
    """Связь с Telegram только по IPv4 и с запасом времени на выгрузку файлов.

    На боевом сервере IPv6 до api.telegram.org не поднимается: каждая попытка
    сначала уходила в него, выгрузка анимации растягивалась и отваливалась по
    таймауту, а человек видел бота молчащим.
    """

    def __init__(self, timeout: float = 120) -> None:
        super().__init__(timeout=timeout)
        self._connector_init["family"] = socket.AF_INET


async def on_error(event: ErrorEvent) -> bool:
    """Просроченный клик по кнопке — не повод для простыни в журнале.

    Telegram даёт на ответ полминуты; если экран собирался дольше (медленная
    выгрузка файла), ответ уже некуда девать — записываем строкой.
    """
    error = event.exception

    if isinstance(error, TelegramBadRequest) and "query is too old" in str(error).lower():
        logger.info("клик устарел, ответ не отправлен")
        return True

    logger.exception("необработанная ошибка: %s", error)

    return True


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.errors.register(on_error)

    # Подписка на канал — требование общее для всех входов, поэтому проверка
    # висит на диспетчере, а не на отдельных роутерах: вешать её на каждый
    # значит однажды завести новый роутер и забыть. Что она пропускает мимо
    # себя и почему — в самом middleware.
    dp.message.middleware(ChannelMiddleware())
    dp.callback_query.middleware(ChannelMiddleware())

    # Управление уехало в мини-приложение: в боте остались витрина
    # (первый экран с кнопкой запуска), пригласительные ссылки и оплата
    # звёздами — её Telegram проводит только через бота. Роутеры входа,
    # кабинета, тарифов, друзей и переводов отключены намеренно: их
    # экраны живут в приложении, и два места для одного и того же
    # расходились бы.
    dp.include_routers(
        # Оплата — ПЕРВОЙ, и это не вкусовщина.
        #
        # Апдейт забирает первый подошедший роутер. Хендлеры состояний
        # (`@router.message(Login.password)` и подобные) подходят под ЛЮБОЕ
        # сообщение в своём состоянии — включая служебное successful_payment.
        # Пока payments стоял восьмым, человек, начавший вводить пароль и
        # оплативший счёт в том же чате, отдавал звёзды в никуда: подписку не
        # продлевали, админам не сообщали, в журнале не было ни строки.
        #
        # Фильтры по типу сообщения на самих хендлерах состояний тоже стоят
        # (так честнее), но порядок надёжнее: он защищает и от хендлера,
        # который допишут завтра.
        payments.router,
        start.router,
        promo.router,
        subscribe.router,
        admin.router,
    )

    return dp


def notify_systemd(message: str) -> None:
    """Строка в NOTIFY_SOCKET. Запущено руками, без systemd — молча выходим."""
    address = os.environ.get("NOTIFY_SOCKET")

    if not address:
        return

    if address.startswith("@"):
        address = "\0" + address[1:]

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.send(message.encode())
    except OSError as error:
        logger.warning("systemd не принял %s: %s", message, error)


async def heartbeat() -> None:
    """Пульс сторожевому таймеру: раз в половину отведённого срока."""
    period = int(os.environ.get("WATCHDOG_USEC", 0)) / 2_000_000

    if not period:
        return

    while True:
        notify_systemd("WATCHDOG=1")
        await asyncio.sleep(period)


async def prepare(bot: Bot, drop_pending: bool = False) -> bool:
    """
    Снимает вебхук и здоровается. False — Telegram недоступен, пробуем позже.

    `drop_pending` — только для самого первого запуска процесса. Раньше он
    стоял всегда, и это стоило денег: Telegram копит апдейты, пока бот лежит,
    и среди них бывает successful_payment. Каждый рестарт (а он штатный —
    Restart=always и watchdog) стирал накопленное вместе с оплатами: звёзды
    списаны, подписки нет, в журнале ни строки. Теперь переподключение
    забирает всё, что накопилось, и доводит до конца.
    """
    try:
        await bot.delete_webhook(drop_pending_updates=drop_pending)
        me = await bot.get_me()
    except TelegramAPIError as error:
        logger.warning("Telegram молчит (%s) — ждём и пробуем снова", error)
        return False

    logger.info("Бот @%s на связи, панель %s", me.username, config.panel_url)

    return True


async def describe(bot: Bot) -> None:
    """Команды и описание в профиле: витрина, без которой опрос всё равно идёт."""
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.set_my_description(BOT_DESCRIPTION)
        await bot.set_my_short_description(BOT_SHORT_DESCRIPTION)
    except TelegramAPIError as error:
        logger.warning("витрина бота не обновилась: %s", error)


async def poll_forever(dp: Dispatcher, bot: Bot) -> None:
    """Опрос, который сам поднимается: авария Telegram не должна ронять службу."""
    # Первый заход снимает возможный мусор от прошлой жизни бота; дальше —
    # ничего не выбрасываем, см. prepare.
    first = True
    while True:
        if not await prepare(bot, drop_pending=first):
            await asyncio.sleep(RETRY_PAUSE)
            continue
        first = False

        await describe(bot)

        try:
            await dp.start_polling(bot)
            return
        except TelegramAPIError as error:
            logger.warning("опрос оборвался (%s) — продолжим через %sс", error, RETRY_PAUSE)
            await asyncio.sleep(RETRY_PAUSE)


async def main() -> None:
    await init_db()

    bot = Bot(
        token=config.token,
        session=BotSession(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = build_dispatcher()

    notify_systemd("READY=1")
    pulse = asyncio.create_task(heartbeat())
    # Письма вдогонку идут своим циклом, а не по событиям: поводы для них —
    # это прошедшее время (сутки молчания, три дня до конца подписки), и
    # заметить их может только тот, кто регулярно смотрит на часы.
    letters = asyncio.create_task(drip.run(bot))

    try:
        await poll_forever(dp, bot)
    finally:
        pulse.cancel()
        letters.cancel()
        await panel.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
