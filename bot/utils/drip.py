"""
Письма вдогонку: бот пишет первым, когда человек остановился на полпути.

Три повода, и все три — про застрявших:

* зашёл в бота и не завёл аккаунт — через сутки предлагаем 20 дней за
  регистрацию (дни начислит сама регистрация, см. handlers/promo.py);
* завёл аккаунт и ни разу не подключился — дарим дни сразу, добивая остаток
  до 20: человеку, который так и не включил VPN, нужен не счёт, а повод
  попробовать;
* подписка кончается — предлагаем продлить и добавляем неделю сверху тем,
  кто сделает это в срок.

Каждое письмо уходит один раз: за это отвечает таблица `nudges`, а не
проверки в коде (первичный ключ «человек — повод»).

Как узнаём, что человек продлил. Бот не видит платежей: СБП и криптой
занимается панель, звёздами — Telegram. Поэтому в момент письма мы
записываем, до какого числа была подписка, а в следующий обход сравниваем.
Выросло — значит оплатил, и неделя начисляется сама. Обратная сторона: дни,
пришедшие переводом от друга, тоже читаются как продление. Ущерб — неделя
доступа в трёхдневном окне, и это дешевле, чем требовать от человека нажать
какую-то кнопку «я оплатил».
"""

import asyncio
from collections import Counter
from datetime import timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from database import models
from keyboards import menus, ui
from utils import assets, panel, texts, timeutils
from utils.logger import logger
from utils.render import media_key


# Как часто просыпаемся. Получасовой шаг: все три повода измеряются днями,
# а частый обход — это лишний тяжёлый запрос к панели.
CHECK_EVERY = 30 * 60

# Первый обход — не сразу после запуска: даём боту подняться, прогреться и
# не устраивать рассылку в секунду перезапуска службы.
FIRST_DELAY = 3 * 60

# Сутки молчания, прежде чем написать первым. Раньше — человек ещё в боте, и
# письмо приходит поверх открытого экрана.
SILENCE = timedelta(hours=24)

# Сколько дней обещаем за регистрацию и до скольких добиваем тому, кто
# завёл аккаунт, но не подключился.
GIFT_DAYS = 20

# За сколько дней до конца подписки предлагаем продлить и сколько дарим за
# продление в срок.
RENEW_AT = 3
RENEW_BONUS = 7
RENEW_WINDOW = timedelta(days=RENEW_AT)

# Пауза между отправками: рассылка не должна упираться в лимиты Telegram.
SEND_PAUSE = 0.3

SIGNUP = "signup"
IDLE = "idle"
RENEW = "renew"


# --------------------------------------------------------------------------
# Обход
# --------------------------------------------------------------------------


async def run(bot: Bot) -> None:
    """Вечный цикл. Сбой одного обхода не должен гасить остальные."""
    await asyncio.sleep(FIRST_DELAY)

    while True:
        try:
            report = await sweep(bot)

            if report:
                logger.info("рассылка: %s", ", ".join(f"{k} {v}" for k, v in report.items()))
        except panel.PanelError as error:
            logger.warning("рассылка отложена, панель молчит: %s", error)
        except Exception:
            logger.exception("рассылка сорвалась")

        await asyncio.sleep(CHECK_EVERY)


async def sweep(bot: Bot | None, dry: bool = False) -> Counter:
    """
    Один обход. `dry` — только посчитать, ничего не отправляя и не даря.

    За обход человек получает не больше одного письма: поводов может совпасть
    несколько, и три сообщения подряд читаются как поломка бота.
    """
    people = await models.audience()
    accounts = {row.login.lower(): row for row in await panel.admin_users()}
    done: Counter = Counter()

    for person in people:
        account = accounts.get(person.login.lower()) if person.login else None

        # Логин известен, а учётки нет: её удалили из панели. Предлагать
        # такому регистрацию заново мы не беремся — молча пропускаем.
        if person.login and account is None:
            continue

        if account is None:
            if await _signup(bot, person, dry):
                done[SIGNUP] += 1
            continue

        if await _bonus(bot, person, account, dry):
            done["bonus"] += 1
            continue

        if await _idle(bot, person, account, dry):
            done[IDLE] += 1
            continue

        if await _renew(bot, person, account, dry):
            done[RENEW] += 1

    return done


def _quiet(person: models.Candidate) -> bool:
    """Прошли ли сутки с первого захода."""
    return timeutils.now() - person.first_seen >= SILENCE


# --------------------------------------------------------------------------
# Поводы
# --------------------------------------------------------------------------


async def _signup(bot: Bot | None, person: models.Candidate, dry: bool) -> bool:
    """Зашёл и не завёл аккаунт: обещаем дни за регистрацию."""
    if not _quiet(person):
        return False

    if await models.get_nudge(person.user_id, SIGNUP) is not None:
        return False

    if dry:
        return True

    sent = await _send(
        bot,
        person.user_id,
        assets.GIFT,
        texts.nudge_signup_text(GIFT_DAYS),
        menus.nudge_signup_menu(),
    )

    if not sent:
        return False

    # Дни здесь не начисляем — начислять некому: аккаунта ещё нет. Обещание
    # ждёт в базе и срабатывает в момент регистрации.
    await models.remember_nudge(person.user_id, SIGNUP, promised_days=GIFT_DAYS)
    logger.info("рассылка: %s обещаны %s дн. за регистрацию", person.user_id, GIFT_DAYS)

    return True


async def _idle(
    bot: Bot | None, person: models.Candidate, account: panel.AdminUser, dry: bool
) -> bool:
    """
    Аккаунт есть, а VPN так и не включили: дарим дни сразу.

    Сразу, а не «после какого-нибудь действия», потому что действие тут ровно
    одно — подключиться, и именно его человек и не делает. Подарок снимает
    последний повод откладывать: дни уже лежат, осталось поставить приложение.
    """
    if not account.never_connected or account.is_free or account.is_frozen:
        return False

    if not _quiet(person):
        return False

    if await models.get_nudge(person.user_id, IDLE) is not None:
        return False

    left = account.days_left or 0
    add = GIFT_DAYS - left

    # Дней и так больше, чем мы дарим: человек купил надолго и просто ещё не
    # дошёл до установки. Такому дарить нечего — ему хватит напоминания в
    # конце срока.
    if add <= 0:
        return False

    if dry:
        return True

    if not await panel.grant_days(account.login, add, reason="дожим: не подключался"):
        logger.warning("рассылка: учётки %s в панели нет, подарок отменён", account.login)
        return False

    sent = await _send(
        bot,
        person.user_id,
        assets.GIFT,
        texts.nudge_idle_text(GIFT_DAYS),
        menus.nudge_idle_menu(),
    )

    await models.remember_nudge(person.user_id, IDLE, promised_days=add)
    await models.claim_nudge(person.user_id, IDLE, add)

    # Наш собственный подарок сдвинул дату окончания. Если человеку в этот же
    # день ушло письмо про конец подписки, следующий обход принял бы этот
    # сдвиг за оплату и выдал ещё неделю — закрываем то обещание здесь.
    await models.claim_nudge(person.user_id, RENEW, 0)

    logger.info(
        "рассылка: %s (%s) подарено %s дн. до %s — не подключался%s",
        person.user_id,
        account.login,
        add,
        GIFT_DAYS,
        "" if sent else ", письмо не дошло",
    )

    return True


async def _renew(
    bot: Bot | None, person: models.Candidate, account: panel.AdminUser, dry: bool
) -> bool:
    """Подписка на исходе: предлагаем продлить с неделей сверху."""
    # Замороженная подписка не кончается: её часы стоят, и напоминание
    # «продлите, осталось три дня» человеку на паузе — просто неправда.
    if account.is_free or account.is_frozen:
        return False

    if account.expires_at is None or account.days_left is None:
        return False

    if not 0 < account.days_left <= RENEW_AT:
        return False

    nudge = await models.get_nudge(person.user_id, RENEW)

    # Письмо про этот же срок уже уходило. Новое разрешаем, только когда
    # подписка с тех пор продлевалась — иначе бот писал бы каждый обход, пока
    # идут последние три дня.
    if nudge is not None and not (
        nudge.expires_snapshot and account.expires_at > nudge.expires_snapshot
    ):
        return False

    if dry:
        return True

    sent = await _send(
        bot,
        person.user_id,
        assets.RENEW,
        texts.nudge_renew_text(account.days_left, RENEW_BONUS),
        menus.nudge_renew_menu(),
    )

    if not sent:
        return False

    await models.remember_nudge(
        person.user_id,
        RENEW,
        promised_days=RENEW_BONUS,
        expires_snapshot=account.expires_at,
    )
    logger.info(
        "рассылка: %s (%s) предложено продление, осталось %s дн.",
        person.user_id,
        account.login,
        account.days_left,
    )

    return True


async def _bonus(
    bot: Bot | None, person: models.Candidate, account: panel.AdminUser, dry: bool
) -> bool:
    """
    Продлил после письма — начисляем обещанную неделю.

    Порядок «сначала дни, потом отметка» выбран сознательно: сбой панели
    оставит обещание открытым, и следующий обход повторит попытку. Обратный
    порядок в той же ситуации молча съел бы подарок.
    """
    nudge = await models.get_nudge(person.user_id, RENEW)

    if nudge is None or not nudge.open or nudge.expires_snapshot is None:
        return False

    if timeutils.now() - nudge.sent_at > RENEW_WINDOW:
        return False

    if account.expires_at is None or account.expires_at <= nudge.expires_snapshot:
        return False

    if dry:
        return True

    if not await panel.grant_days(
        account.login, nudge.promised_days or RENEW_BONUS, reason="бонус за продление"
    ):
        logger.warning("рассылка: бонус за продление некому начислить (%s)", account.login)
        return False

    days = nudge.promised_days or RENEW_BONUS
    await models.claim_nudge(person.user_id, RENEW, days)

    await _send(
        bot,
        person.user_id,
        assets.GIFT,
        texts.renew_bonus_text(days),
        menus.gift_menu(),
    )

    logger.info("рассылка: %s (%s) начислен бонус %s дн.", person.user_id, account.login, days)

    return True


# --------------------------------------------------------------------------
# Отправка
# --------------------------------------------------------------------------


async def _send(
    bot: Bot | None,
    user_id: int,
    animation: Path,
    text: str,
    markup: InlineKeyboardMarkup,
) -> bool:
    """
    Письмо с видео. False — не дошло и повторять смысла нет.

    Видео берём известным file_id, а первый раз выгружаем файлом — тем же
    кэшем, что и экраны бота (таблица media). Заблокировавший бота человек
    считается «доставленным»: писать ему больше некуда, и повторять попытку
    каждый обход незачем.
    """
    if bot is None:
        return False

    key = media_key(animation)
    source = await models.get_media(key)

    # Попыток немного и все разные: протухший file_id, премиум-эмодзи,
    # «подождите столько-то секунд». Общий счётчик держит рассылку от
    # хождения по кругу, если Telegram отвечает одним и тем же.
    for _ in range(4):
        body = text if ui.custom_emoji_enabled() else ui.strip_custom_emoji(text)

        try:
            sent = await bot.send_animation(
                user_id,
                source or FSInputFile(str(animation)),
                caption=body,
                reply_markup=markup,
            )
        except TelegramForbiddenError:
            # Бот закрыт или удалён: писать больше некуда, и повторять эту
            # попытку каждый обход незачем — считаем письмо доставленным.
            logger.info("рассылка: %s закрыл бота", user_id)
            return True
        except TelegramRetryAfter as error:
            await asyncio.sleep(error.retry_after + 1)
            continue
        except TelegramBadRequest as error:
            if ui.premium_rejected(error):
                ui.disable_custom_emoji()
                continue

            if source:
                # file_id больше не годится — забываем и пробуем файлом.
                logger.warning("рассылка: file_id для %s протух", animation.name)
                await models.forget_media(key)
                source = None
                continue

            logger.warning("рассылка: письмо %s не ушло — %s", user_id, error)
            return False
        except TelegramAPIError as error:
            logger.warning("рассылка: Telegram не принял письмо %s — %s", user_id, error)
            return False

        if sent.animation:
            await models.save_media(key, sent.animation.file_id)

        await asyncio.sleep(SEND_PAUSE)

        return True

    return False
