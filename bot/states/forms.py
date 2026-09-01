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


class Transfer(StatesGroup):
    """Передача дней другу: сначала кому, потом сколько."""

    recipient = State()
    days = State()


class BuyDaily(StatesGroup):
    """Посуточный тариф: спрашиваем, на сколько дней."""

    days = State()
