from aiogram.fsm.state import State, StatesGroup


class Register(StatesGroup):
    login = State()
    password = State()
    confirm = State()


class Login(StatesGroup):
    login = State()
    password = State()


class ChangePassword(StatesGroup):
    current = State()
    fresh = State()


class Support(StatesGroup):
    message = State()
