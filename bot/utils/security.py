"""Проверка логина и пароля до обращения к панели.

Пароли бот не хранит и не сверяет — этим занимается панель. Здесь только
правила, о которых лучше сказать сразу, не гоняя человека к серверу.
"""

import re


# Те же символы, что принимает панель: латиница, цифры, дефис, точка, «_».
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9._-]{4,32}$")

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def login_error(login: str) -> str | None:
    if not LOGIN_PATTERN.fullmatch(login):
        return "Логин: латиница, цифры, «.», «-», «_», от 4 до 32 символов."

    return None


def password_error(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль от {MIN_PASSWORD_LENGTH} символов."

    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Пароль до {MAX_PASSWORD_LENGTH} символов."

    if any(char.isspace() for char in password):
        return "Пароль без пробелов."

    return None
