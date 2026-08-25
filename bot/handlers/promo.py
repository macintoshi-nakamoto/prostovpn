from html import escape
from urllib.parse import urlencode

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from config.settings import config
from database import models
from handlers.common import show_screen
from keyboards.menus import iphone_menu, promo_granted_menu, promo_menu
from utils import assets, panel, screens, texts, timeutils
from utils.logger import logger


router = Router()

PROMO_PREFIX = "promo_"


def promo_code_from_payload(payload: str | None) -> str | None:
    if not payload or not payload.startswith(PROMO_PREFIX):
        return None

    code = payload[len(PROMO_PREFIX) :].strip()

    if not code or len(code) > 64:
        return None
    if not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in code):
        return None

    return code


async def remember_from_payload(user_id: int, payload: str | None) -> "models.Promo | None":
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

    if await models.pending_promo(user_id) is None:
        session = await models.get_session(user_id)
        login = session.panel_login if session else await models.last_login(user_id)
        if login:
            return None

    await models.remember_promo(user_id, code)
    logger.info("промо %s: переход %s", code, user_id)

    return promo


async def show_offer(event, promo) -> None:
    await show_screen(
        event,
        lambda file_id: screens.promo(file_id, promo.days),
        promo_menu(promo_url(promo.code)),
        text=texts.promo_text(promo.days),
        animation=assets.PROMO,
    )


async def offer_promo(message: Message, payload: str | None) -> bool:
    promo = await remember_from_payload(message.from_user.id, payload)

    if promo is None:
        if promo_code_from_payload(payload):
            await message.answer(texts.promo_used_text())
        return False

    await show_offer(message, promo)

    return True


async def grant_pending(message: Message, panel_login: str) -> int:
    promo = await models.pending_promo(message.from_user.id)

    if promo is None:
        return 0

    try:
        granted = await panel.grant_days(
            panel_login, promo.days, reason=f"промо {promo.code}"
        )
    except panel.PanelError as error:
        logger.warning("промо %s: дни не начислены (%s)", promo.code, error)
        return 0

    if not granted:
        logger.warning("промо %s: учётка %s в панели не найдена", promo.code, panel_login)
        return 0

    await models.claim_promo(message.from_user.id, panel_login, promo.days)
    logger.info("промо %s: %s дн. начислены %s", promo.code, promo.days, panel_login)

    await message.answer(
        texts.promo_granted_text(promo.days),
        reply_markup=promo_granted_menu(share_url(promo), promo_url(promo.code)),
    )

    return promo.days


def share_url(promo) -> str:
    pitch = (
        f"Пользуюсь Prosto VPN — держи {timeutils.plural_days(promo.days)} "
        "бесплатно по моей ссылке"
    )
    return "https://t.me/share/url?" + urlencode({"url": promo_url(promo.code), "text": pitch})


@router.callback_query(F.data == "iphone")
async def iphone(callback: CallbackQuery) -> None:
    authorized = await models.get_session(callback.from_user.id) is not None

    await show_screen(
        callback,
        screens.iphone,
        iphone_menu(authorized),
        text=texts.iphone_text(),
        animation=assets.ABOUT,
    )
    await callback.answer()


def promo_url(code: str) -> str:
    return f"https://t.me/{config.bot_username}?start={PROMO_PREFIX}{code}"


@router.message(Command("promo"))
async def promo_command(message: Message, command: CommandObject) -> None:
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
