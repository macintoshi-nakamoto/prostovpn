from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import User
from .errors import PanelError

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
DIGITS = "0123456789"

LOGIN_PREFIX = "pv"
LOGIN_DIGITS = 7
PASSWORD_GROUPS = 3
PASSWORD_GROUP_LEN = 4


def gen_login() -> str:
    return LOGIN_PREFIX + "".join(secrets.choice(DIGITS) for _ in range(LOGIN_DIGITS))


def gen_password() -> str:
    return "-".join(
        "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_GROUP_LEN))
        for _ in range(PASSWORD_GROUPS)
    )


def free_login(db: OrmSession, attempts: int = 100) -> str:
    for _ in range(attempts):
        login = gen_login()
        if db.scalar(select(User.id).where(User.login == login)) is None:
            return login
    raise PanelError("не удалось подобрать свободный логин")
