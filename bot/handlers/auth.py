"""Вход, регистрация и смена пароля. Учётки живут в панели, не в боте."""

import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import models
from handlers.common import show_cabinet, show_gate, show_start
from keyboards.menus import cancel_menu
from keyboards.ui import tg
from states.forms import ChangePassword, Login, Register
from utils import assets, panel, texts
from utils.render import show
from utils.security import login_error, password_error


router = Router()


MAX_ATTEMPTS = 5
LOCK_SECONDS = 10 * 60

_failures: dict[int, list[float]] = {}


def _fresh(user_id: int) -> list[float]:
    now = time.monotonic()
    attempts = [stamp for stamp in _failures.get(user_id, []) if now - stamp < LOCK_SECONDS]
    _failures[user_id] = attempts

    return attempts


def _register_failure(user_id: int) -> int:
    attempts = _fresh(user_id)
    attempts.append(time.monotonic())

    return MAX_ATTEMPTS - len(attempts)


def _locked_for(user_id: int) -> int:
    attempts = _fresh(user_id)

    if len(attempts) < MAX_ATTEMPTS:
        return 0

    return int(LOCK_SECONDS - (time.monotonic() - attempts[0])) + 1


async def _hide(message: Message) -> None:
    """Убирает из чата сообщение с паролем."""
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


def _form(title: str, hint: str):
    return lambda: (f"{title}\n\n{hint}", cancel_menu())


async def _warn(message: Message, text: str) -> None:
    await message.answer(f'{tg("warn")} {text}')


# --------------------------------------------------------------------------
# Регистрация
# --------------------------------------------------------------------------


@router.callback_query(F.data == "register")
async def register_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Register.login)

    await show(
        callback,
        _form(
            f'{tg("profile")} <b>Регистрация</b>',
            "Придумайте логин: латиница, цифры, «.», «-», «_».",
        ),
        animation=assets.LOGIN_LOGIN,
    )

    await callback.answer()


@router.message(Register.login)
async def register_login(message: Message, state: FSMContext) -> None:
    login = (message.text or "").strip()
    error = login_error(login)

    if error:
        await _warn(message, error)
        return

    await state.update_data(login=login)
    await state.set_state(Register.password)

    await show(
        message,
        _form(
            f'{tg("key")} <b>Регистрация</b>',
            f"Логин: <b>{login}</b>\n\nПридумайте пароль — от 8 символов.",
        ),
        animation=assets.LOGIN_PASSWORD,
    )


@router.message(Register.password)
async def register_password(message: Message, state: FSMContext) -> None:
    password = message.text or ""
    await _hide(message)

    error = password_error(password)

    if error:
        await _warn(message, error)
        return

    await state.update_data(password=password)
    await state.set_state(Register.confirm)

    await show(
        message,
        _form(f'{tg("key")} <b>Регистрация</b>', "Повторите пароль."),
        animation=assets.LOGIN_PASSWORD,
    )


@router.message(Register.confirm)
async def register_confirm(message: Message, state: FSMContext) -> None:
    repeat = message.text or ""
    await _hide(message)

    data = await state.get_data()

    if repeat != data.get("password"):
        await state.set_state(Register.password)
        await _warn(message, "Пароли не совпали. Придумайте пароль заново.")
        return

    login = data["login"]
    password = data["password"]

    try:
        await panel.create_account(login, password)
        session = await panel.login(login, password)
    except panel.PanelError as error:
        await state.set_state(Register.login)
        await _warn(message, f"{texts.panel_error(error)}\n\nПридумайте другой логин.")
        return

    await models.save_session(message.from_user.id, session.login, session.token, session.expires_at)
    await state.clear()

    await message.answer(
        f'{tg("check")} <b>Аккаунт создан</b>\n\n'
        f"Логин: <code>{login}</code>\n"
        "Эти же логин и пароль работают на сайте и в приложении."
    )

    await show_cabinet(message, message.from_user.id)


# --------------------------------------------------------------------------
# Вход
# --------------------------------------------------------------------------


@router.callback_query(F.data == "login")
async def login_start(callback: CallbackQuery, state: FSMContext) -> None:
    locked = _locked_for(callback.from_user.id)

    if locked:
        await callback.answer(
            f"Слишком много попыток. Повторите через {locked // 60 + 1} мин.",
            show_alert=True,
        )
        return

    known = await models.last_login(callback.from_user.id)
    hint = f"Прошлый логин: <b>{known}</b>\n\n" if known else ""

    await state.set_state(Login.login)

    await show(
        callback,
        _form(f'{tg("key")} <b>Вход</b>', f"{hint}Введите логин."),
        animation=assets.LOGIN_LOGIN,
    )

    await callback.answer()


@router.message(Login.login)
async def login_login(message: Message, state: FSMContext) -> None:
    login = (message.text or "").strip()

    if not login:
        await _warn(message, "Введите логин одной строкой.")
        return

    await state.update_data(login=login)
    await state.set_state(Login.password)

    await show(
        message,
        _form(f'{tg("key")} <b>Вход</b>', f"Логин: <b>{login}</b>\n\nВведите пароль."),
        animation=assets.LOGIN_PASSWORD,
    )


@router.message(Login.password)
async def login_password(message: Message, state: FSMContext) -> None:
    password = message.text or ""
    await _hide(message)

    data = await state.get_data()
    login = data.get("login", "")

    try:
        session = await panel.login(login, password)
    except panel.PanelError as error:
        if error.status in (401, 403):
            left = _register_failure(message.from_user.id)

            if left <= 0:
                await state.clear()
                await _warn(message, "Слишком много попыток. Вход закрыт на 10 минут.")
                return

            await _warn(message, f"{texts.panel_error(error)} Осталось попыток: {left}.")
            return

        await state.clear()
        await _warn(message, texts.panel_error(error))
        await show_gate(message, message.from_user.id)
        return

    await models.save_session(message.from_user.id, session.login, session.token, session.expires_at)
    _failures.pop(message.from_user.id, None)
    await state.clear()

    await show_cabinet(message, message.from_user.id)


@router.callback_query(F.data == "logout")
async def logout(callback: CallbackQuery, state: FSMContext) -> None:
    session = await models.get_session(callback.from_user.id)

    if session:
        await panel.logout(session.token)

    await models.close_session(callback.from_user.id)
    await state.clear()

    await callback.answer("Вы вышли")
    await show_start(callback)


# --------------------------------------------------------------------------
# Смена пароля
# --------------------------------------------------------------------------


@router.callback_query(F.data == "password")
async def password_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await models.get_session(callback.from_user.id):
        await show_gate(callback, callback.from_user.id)
        await callback.answer()
        return

    await state.set_state(ChangePassword.current)

    await show(
        callback,
        _form(f'{tg("key")} <b>Смена пароля</b>', "Введите текущий пароль."),
        animation=assets.PASSWORD,
    )

    await callback.answer()


@router.message(ChangePassword.current)
async def password_current(message: Message, state: FSMContext) -> None:
    password = message.text or ""
    await _hide(message)

    await state.update_data(current=password)
    await state.set_state(ChangePassword.fresh)

    await show(
        message,
        _form(f'{tg("key")} <b>Смена пароля</b>', "Введите новый пароль — от 8 символов."),
        animation=assets.PASSWORD,
    )


@router.message(ChangePassword.fresh)
async def password_fresh(message: Message, state: FSMContext) -> None:
    password = message.text or ""
    await _hide(message)

    error = password_error(password)

    if error:
        await _warn(message, error)
        return

    session = await models.get_session(message.from_user.id)

    if not session:
        await state.clear()
        await show_gate(message, message.from_user.id)
        return

    data = await state.get_data()

    try:
        await panel.change_password(session.token, data.get("current", ""), password)
    except panel.PanelError as error:
        await state.set_state(ChangePassword.current)
        await _warn(message, f"{texts.panel_error(error)}\n\nВведите текущий пароль ещё раз.")
        return

    await state.clear()
    await message.answer(f'{tg("check")} Пароль изменён.')

    # Смена пароля гасит все сессии панели, включая нашу: входим заново
    # с новым паролем, иначе кабинет тут же попросил бы залогиниться.
    try:
        fresh_session = await panel.login(session.panel_login, password)
    except panel.PanelError:
        await models.close_session(message.from_user.id)
        await show_gate(message, message.from_user.id)
        return

    await models.save_session(
        message.from_user.id,
        fresh_session.login,
        fresh_session.token,
        fresh_session.expires_at,
    )

    await show_cabinet(message, message.from_user.id)


# --------------------------------------------------------------------------
# Отмена формы
# --------------------------------------------------------------------------


@router.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    if await models.get_session(callback.from_user.id):
        await show_cabinet(callback, callback.from_user.id)
    else:
        await show_gate(callback, callback.from_user.id)

    await callback.answer()
