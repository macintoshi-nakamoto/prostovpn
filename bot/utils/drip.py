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
import datetime as dt
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

# Учётка «новая», если создана не раньше обещания. Час запаса — на
# округление секунд в базе бота и на то, что человек мог завести аккаунт
# в мини-аппе за минуту до того, как дошёл до ссылки.
NEW_ACCOUNT_SLACK = timedelta(hours=1)


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
    rows = await panel.admin_users()
    accounts = {row.login.lower(): row for row in rows}
    # Аккаунт заводят в мини-приложении, и бот про это узнаёт единственным
    # способом: панель привязала Telegram к учётке при регистрации.
    by_telegram = {row.telegram_id: row for row in rows if row.telegram_id}
    done: Counter = Counter()

    for person in people:
        account = accounts.get(person.login.lower()) if person.login else None

        if account is None:
            account = by_telegram.get(person.user_id)

        # Логин известен, а учётки нет: её удалили из панели. Предлагать
        # такому регистрацию заново мы не беремся — молча пропускаем.
        if person.login and account is None:
            continue

        if account is not None and await _promo_claim(bot, person, account, dry):
            done["promo"] += 1
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


def _born_after(account: panel.AdminUser, moment: dt.datetime) -> bool:
    """
    Учётка появилась после этого момента.

    Панель отдаёт время в наивном UTC, бот живёт по местному наивному
    (timeutils.now()): `.astimezone()` у наивного времени берёт системный
    пояс, так что сравнение верно на любом сервере.
    """
    if account.created_at is None:
        return True  # старая панель без createdAt — ведём себя как раньше

    moment_utc = moment.astimezone(dt.timezone.utc).replace(tzinfo=None)

    return account.created_at >= moment_utc - NEW_ACCOUNT_SLACK


async def _promo_claim(
    bot: Bot | None,
    person: models.Candidate,
    account: panel.AdminUser,
    dry: bool,
) -> bool:
    """
    Начисляет обещанное тому, кто завёл аккаунт в приложении.

    Раньше это делала регистрация в боте — теперь её нет, и единственный
    надёжный признак «аккаунт появился» приходит из панели: она привязала
    Telegram к учётке. Обещаний может быть два сразу (пригласительная
    ссылка и письмо вдогонку) — берём большее, а не сумму: иначе человек,
    получивший письмо и перешедший по чужой ссылке, унёс бы оба подарка.
    """
    promo = await models.pending_promo(person.user_id)
    nudge = await models.get_nudge(person.user_id, SIGNUP)
    promised = nudge.promised_days if nudge and nudge.open else 0

    # Подарок только новому аккаунту (см. handlers/promo.py). Учётка старше
    # обещания — это давний клиент, переславший ссылку самому себе (или
    # клиент с сайта, которого мини-апп привязал к Telegram уже после
    # письма): переход закрываем без дней, чтобы обходчик не возвращался
    # к нему каждые полчаса.
    stale_promo = (
        promo is not None
        and promo.visited_at is not None
        and not _born_after(account, promo.visited_at)
    )
    stale_signup = bool(promised) and nudge is not None and not _born_after(account, nudge.sent_at)

    if stale_promo or stale_signup:
        if dry:
            logger.info("подарок: %s старше обещания, не дарим (dry)", account.login)
        else:
            if stale_promo:
                await models.claim_promo(person.user_id, account.login, 0)
                logger.info(
                    "промо %s: учётка %s старше перехода, дни не начислены",
                    promo.code,
                    account.login,
                )
            if stale_signup:
                await models.claim_nudge(person.user_id, SIGNUP, 0)
                logger.info("дожим: учётка %s старше письма, дни не начислены", account.login)
        if stale_promo:
            promo = None
        if stale_signup:
            promised = 0

    days = max(promo.days if promo else 0, promised)

    if not days:
        return False
    if dry:
        return True

    reason = f"промо {promo.code}" if promo else "дожим: регистрация"

    try:
        granted = await panel.grant_days(account.login, days, reason=reason)
    except panel.PanelError as error:
        logger.warning("подарок (%s): дни не начислены (%s)", reason, error)
        return False

    if not granted:
        logger.warning("подарок (%s): учётки %s в панели нет", reason, account.login)
        return False

    if promo:
        await models.claim_promo(person.user_id, account.login, days)
    if promised:
        await models.claim_nudge(person.user_id, "signup", days)

    logger.info("подарок (%s): %s дн. начислены %s", reason, days, account.login)

    if bot is not None:
        # Кнопка одна — открыть приложение: подключение, тариф и всё
        # остальное живут там.
        await _send(
            bot,
            person.user_id,
            assets.MINIAPP,
            texts.promo_granted_text(days),
            menus.start_menu(),
        )

    return True


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
