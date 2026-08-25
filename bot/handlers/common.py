from collections.abc import Callable
from pathlib import Path

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from database import models
from database.models import Session
from keyboards.menus import (
    back_menu,
    cabinet_menu,
    gate_menu,
    main_menu,
    start_menu,
    subscribe_menu,
)
from keyboards.ui import tg
from utils import assets, panel, render, screens, texts
from utils.render import media_key


Event = Message | CallbackQuery

Blocks = Callable[[str | None], list[dict]]


async def media_id(path: Path) -> str | None:
    return await models.get_media(media_key(path))


async def show_screen(
    event: Event,
    blocks: Blocks,
    markup: InlineKeyboardMarkup,
    *,
    text: str,
    animation: Path | None = None,
) -> None:
    file_id = await media_id(animation) if animation else None

    if (animation is None or file_id) and await render.show_rich(event, blocks(file_id), markup):
        return

    await render.show(event, lambda: (text, markup), animation=animation)


async def show_start(event: Event) -> None:
    await show_screen(
        event,
        screens.start,
        start_menu(),
        text=texts.start_text(),
        animation=assets.WELCOME,
    )


async def show_gate(event: Event, user_id: int) -> None:
    login = await models.last_login(user_id)

    await show_screen(
        event,
        lambda file_id: screens.gate(file_id, login),
        gate_menu(bool(login)),
        text=texts.gate_text(login),
        animation=assets.GATE,
    )


async def show_subscribe(event: Event, days: int | None = None) -> None:
    await show_screen(
        event,
        lambda file_id: screens.subscribe(file_id, days),
        subscribe_menu(),
        text=texts.subscribe_text(days),
        animation=assets.SUBSCRIBE,
    )


async def show_error(event: Event, message: str, target: str = "home") -> None:
    await render.show(
        event,
        lambda: (f'{tg("warn")} {message}', back_menu(target, "Обновить")),
    )


async def fetch_account(event: Event, session: Session) -> panel.Account | None:
    try:
        return await panel.account(session.token)
    except panel.PanelError as error:
        if error.status in (401, 403):
            await models.close_session(session.user_id)
            await show_gate(event, session.user_id)
        else:
            await show_error(event, texts.panel_error(error))

        return None


async def show_home(event: Event, user_id: int) -> None:
    session = await models.get_session(user_id)

    if not session:
        await show_start(event)
        return

    account = await fetch_account(event, session)

    if not account:
        return

    await show_screen(
        event,
        lambda file_id: screens.main(file_id, account),
        main_menu(),
        text=texts.main_text(account),
        animation=assets.MENU,
    )


async def show_cabinet(event: Event, user_id: int) -> None:
    session = await models.get_session(user_id)

    if not session:
        await show_gate(event, user_id)
        return

    account = await fetch_account(event, session)

    if not account:
        return

    await show_screen(
        event,
        lambda file_id: screens.cabinet(file_id, account),
        cabinet_menu(account.active, ios=account.ios_access),
        text=texts.cabinet_text(account),
        animation=assets.cabinet(account.active),
    )
