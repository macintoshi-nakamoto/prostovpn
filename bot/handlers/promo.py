"""
Пригласительная ссылка с бесплатным периодом.

Ссылка — обычный deep-link телеграма: t.me/<бот>?start=promo_<КОД>. Всё, что
она делает, — оставляет отметку «этот человек пришёл по ссылке». Дни даёт
регистрация, и только она: иначе бонус доставался бы и тем, кто у нас давно,
а таким ссылку достаточно переслать самому себе.

Почему отметка живёт в базе бота, а не в панели: ссылка целиком телеграмная,
и панели про неё знать нечего. Панель получает обычное продление без денег —
ровно то же, что администратор делает руками.
"""

from html import escape
from urllib.parse import urlencode

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from config.settings import config
from database import models
from handlers.common import show_screen
from keyboards.menus import gift_menu, iphone_menu, promo_granted_menu, promo_menu
from utils import assets, panel, screens, texts, timeutils
from utils.logger import logger


router = Router()

PROMO_PREFIX = "promo_"


def promo_code_from_payload(payload: str | None) -> str | None:
    """Код из /start. Мусор и чужие форматы — None."""
    if not payload or not payload.startswith(PROMO_PREFIX):
        return None

    code = payload[len(PROMO_PREFIX) :].strip()

    # Код уезжает в SQL и в текст сообщения. Пускаем только то, из чего мы
    # его сами и составляем: буквы, цифры, дефис.
    if not code or len(code) > 64:
        return None
    if not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in code):
        return None

    return code


async def remember_from_payload(user_id: int, payload: str | None) -> "models.Promo | None":
    """
    Проверяет ссылку из /start и записывает переход. Ничего не показывает.

    Отдельно от показа экрана, потому что первым эту ссылку видит middleware
    подписки: он останавливает апдейт до хендлера, и разобрать её больше
    некому. Повторный вызов безвреден — запись перехода идемпотентна.
    """
    code = promo_code_from_payload(payload)

    if not code:
        return None

    promo = await models.get_promo(code)

    if promo is None:
        logger.info("промо: неизвестный код %r от %s", code, user_id)
        return None

    if not promo.alive:
        logger.info("промо %s: срок вышел, пришёл %s", code, user_id)
        return None

    # Подарок только новому аккаунту. Давнему клиенту ссылку достаточно
    # переслать самому себе, поэтому проверяем, знаем ли мы его логин.
    if await models.pending_promo(user_id) is None:
        session = await models.get_session(user_id)
        login = session.panel_login if session else await models.last_login(user_id)
        if login:
            return None

    await models.remember_promo(user_id, code)
    logger.info("промо %s: переход %s", code, user_id)

    return promo


async def show_offer(event, promo) -> None:
    """Экран подарка: что дают и как забрать."""
    await show_screen(
        event,
        lambda file_id: screens.promo(file_id, promo.days),
        promo_menu(promo_url(promo.code)),
        text=texts.promo_text(promo.days),
        # Своя заставка, а не общая от входа: по этой ссылке человек приходит
        # с рекламы и видит бота впервые — первый кадр должен говорить про
        # подарок, а не про форму логина. Звуковой дорожки в файле нет,
        # телеграм показывает его как гифку и без звука.
        animation=assets.PROMO,
    )


async def offer_promo(message: Message, payload: str | None) -> bool:
    """
    Показывает экран подарка. False — обычный первый экран.

    Молча отказываемся во всех случаях, когда дарить нечего: кода нет, срок
    вышел, подарок уже получен. Человек при этом оказывается в боте, а не в
    сообщении об ошибке.
    """
    promo = await remember_from_payload(message.from_user.id, payload)

    if promo is None:
        # Ссылка была, но подарок не положен — говорим прямо, иначе человек
        # будет ждать дни, которые не придут.
        if promo_code_from_payload(payload):
            await message.answer(texts.promo_used_text())
        return False

    await show_offer(message, promo)

    return True


async def grant_pending(message: Message, panel_login: str) -> int:
    """
    Начисляет обещанное сразу после регистрации. 0 — начислять нечего.

    Обещаний может быть два сразу: пригласительная ссылка и письмо вдогонку
    («зашли и не зарегистрировались — дарим 20 дней»). Они не складываются, а
    перекрывают друг друга — берём большее. Складывать нельзя: человек,
    получивший письмо и потом перешедший по чужой ссылке, унёс бы 34 дня.

    Сбой панели гасим и возвращаем 0: обещания при этом остаются открытыми, и
    следующий заход предложит подарок снова. Ронять здесь регистрацию нельзя —
    аккаунт уже создан.
    """
    user_id = message.from_user.id
    promo = await models.pending_promo(user_id)
    promised = await models.promised_days(user_id, "signup")
    days = max(promo.days if promo else 0, promised)

    if not days:
        return 0

    reason = f"промо {promo.code}" if promo else "дожим: регистрация"

    try:
        granted = await panel.grant_days(panel_login, days, reason=reason)
    except panel.PanelError as error:
        logger.warning("подарок (%s): дни не начислены (%s)", reason, error)
        return 0

    if not granted:
        logger.warning("подарок (%s): учётки %s в панели нет", reason, panel_login)
        return 0

    if promo:
        await models.claim_promo(user_id, panel_login, days)

    if promised:
        await models.claim_nudge(user_id, "signup", days)

    logger.info("подарок (%s): %s дн. начислены %s", reason, days, panel_login)

    # Пришедшему по ссылке есть чем поделиться — ему показываем ту же ссылку.
    # Вернувшемуся по письму делиться нечем: у него обычный экран подарка.
    if promo:
        await message.answer(
            texts.promo_granted_text(days),
            reply_markup=promo_granted_menu(share_url(promo), promo_url(promo.code)),
        )
    else:
        await message.answer(texts.gift_granted_text(days), reply_markup=gift_menu())

    return days


def share_url(promo) -> str:
    """
    Ссылка «поделиться» для телеграма: он сам покажет выбор чата.

    Ведёт на ту же промо-ссылку, по которой человек пришёл сам, — в этом и
    смысл: друг получает такой же подарок, и цепочка идёт дальше, пока
    ссылка жива.
    """
    pitch = (
        f"Пользуюсь Prosto VPN — держи {timeutils.plural_days(promo.days)} "
        "бесплатно по моей ссылке"
    )
    return "https://t.me/share/url?" + urlencode({"url": promo_url(promo.code), "text": pitch})


@router.callback_query(F.data == "iphone")
async def iphone(callback: CallbackQuery) -> None:
    """Экран установки для iPhone. Приложения нет — есть ключ AmneziaVPN."""
    authorized = await models.get_session(callback.from_user.id) is not None

    await show_screen(
        callback,
        screens.iphone,
        iphone_menu(authorized),
        text=texts.iphone_text(),
        animation=assets.ABOUT,
    )
    await callback.answer()


# --------------------------------------------------------------------------
# Администратору
# --------------------------------------------------------------------------


def promo_url(code: str) -> str:
    return f"https://t.me/{config.bot_username}?start={PROMO_PREFIX}{code}"


@router.message(Command("promo"))
async def promo_command(message: Message, command: CommandObject) -> None:
    """
    Создать ссылку или посмотреть, что с ней.

        /promo                       — список ссылок
        /promo КОД 14 10             — КОД даёт 14 дней, ссылка живёт 10 суток
    """
    if message.from_user.id not in config.admin_ids:
        return

    args = (command.args or "").split()

    if not args:
        rows = await models.all_promos()

        if not rows:
            await message.answer(
                "Ссылок нет.\n\nСоздать: <code>/promo КОД ДНЕЙ СРОК</code>\n"
                "Например: <code>/promo WELCOME14 14 10</code>"
            )
            return

        lines = []
        for promo in rows:
            visits, claims = await models.promo_stats(promo.code)
            state = "действует" if promo.alive else "истекла"
            lines.append(
                f"<code>{escape(promo.code)}</code> — {promo.days} дн., "
                f"до {timeutils.human_date(promo.expires_at)} ({state})\n"
                f"переходов: {visits}, начислено: {claims}\n"
                f"{escape(promo_url(promo.code))}"
            )

        await message.answer("\n\n".join(lines))
        return

    code = promo_code_from_payload(PROMO_PREFIX + args[0])

    if not code:
        await message.answer("В коде можно только латиницу, цифры и дефис.")
        return

    days = int(args[1]) if len(args) > 1 and args[1].isdigit() else 14
    ttl = int(args[2]) if len(args) > 2 and args[2].isdigit() else 10

    if not (1 <= days <= 365) or not (1 <= ttl <= 365):
        await message.answer("Дней и срок — от 1 до 365.")
        return

    promo = await models.create_promo(code, days=days, ttl_days=ttl)
    logger.info("промо %s: создана админом %s", code, message.from_user.id)

    await message.answer(
        f"Ссылка готова: <b>{timeutils.plural_days(promo.days)}</b> "
        f"новому аккаунту, действует до {timeutils.human_date(promo.expires_at)}.\n\n"
        f"<code>{escape(promo_url(code))}</code>"
    )
