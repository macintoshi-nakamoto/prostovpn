"""
Логин и пароль, которые человек получает после оплаты.

Это ровно две строки, которые он увидит за всю жизнь подписки: ни ключей,
ни конфигов, ни ссылок `vpn://` ему не показывают нигде — ни на сайте, ни в
письме, ни в приложении. Поэтому обе строки обязаны переживать диктовку по
телефону.

Отсюда алфавит без `0`, `o`, `1`, `l` и `i`: «эл» и «ай» на слух не
отличаются, а ноль от буквы «о» не отличается ещё и на экране. Логин —
только цифры после префикса `pv`: цифру продиктовать нельзя неправильно.
Пароль — три группы по четыре символа через дефис: группами он читается
вслух и набирается на телефоне без ошибок, а 31^12 вариантов достаточно,
чтобы подбор не имел смысла.
"""

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
    """Логин вида pv4820193."""
    return LOGIN_PREFIX + "".join(secrets.choice(DIGITS) for _ in range(LOGIN_DIGITS))


def gen_password() -> str:
    """Пароль вида k3np-7hqm-2rxa."""
    return "-".join(
        "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_GROUP_LEN))
        for _ in range(PASSWORD_GROUPS)
    )


def free_login(db: OrmSession, attempts: int = 100) -> str:
    """
    Свободный логин.

    Проверка по базе в цикле, а не «десять миллионов вариантов, коллизия
    невероятна»: на десяти тысячах клиентов вероятность совпадения уже
    заметна, а падение здесь означает потерянную оплату.
    """
    for _ in range(attempts):
        login = gen_login()
        if db.scalar(select(User.id).where(User.login == login)) is None:
            return login
    raise PanelError("не удалось подобрать свободный логин")
