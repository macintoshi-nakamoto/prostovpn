"""
Пароли, токены и адрес клиента.

Основной алгоритм — argon2id (m=64 МБ, t=3, p=1): победитель Password
Hashing Competition и то, что сейчас рекомендует OWASP. Он дороже для
видеокарты, чем scrypt с теми же настройками, а это ровно то, чем
занимается тот, кто утащил базу.

Рядом остаётся scrypt из стандартной библиотеки. Две причины. Первая —
совместимость: в уже развёрнутых панелях лежат scrypt-хэши, и вход не
должен сломаться от обновления; при следующем успешном входе хэш молча
переезжает на argon2id. Вторая — argon2-cffi ставится колесом, но на
экзотической платформе может не собраться, и панель обязана подняться
и без него, пусть и на алгоритме послабее.

Сравнение всегда постоянного времени, иначе по времени ответа подбирается
хэш.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import secrets

from fastapi import Request

log = logging.getLogger("panel.security")

try:  # pragma: no cover - зависит от площадки, а не от логики
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError
    from argon2.low_level import Type as _Argon2Type

    # m=64 МБ, t=3, p=1 — как в задании и в рекомендациях OWASP 2024.
    _ARGON2 = PasswordHasher(
        time_cost=3, memory_cost=64 * 1024, parallelism=1, hash_len=32, salt_len=16,
        type=_Argon2Type.ID,
    )
except Exception:  # pragma: no cover
    _ARGON2 = None
    InvalidHashError = VerificationError = Exception  # type: ignore[misc,assignment]
    log.warning(
        "argon2-cffi недоступен, пароли хэшируются scrypt. "
        "Поставьте пакет из requirements.txt на боевом сервере."
    )

# Параметры scrypt: N=2**15 держит подбор дорогим, но вход остаётся быстрым.
_N = 2 ** 15
_R = 8
_P = 1
_DK_LEN = 32
_SALT_LEN = 16

# scrypt при N=2**15, r=8 требует ~32 МБ, а OpenSSL по умолчанию столько же
# и разрешает — впритык, из-за чего вход падал с «digital envelope routines».
# Задаём лимит явно с запасом.
_MAXMEM = 128 * 1024 * 1024


def hash_password(password: str) -> str:
    if _ARGON2 is not None:
        return _ARGON2.hash(password)
    return _hash_scrypt(password)


def _hash_scrypt(password: str) -> str:
    salt = secrets.token_bytes(_SALT_LEN)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DK_LEN, maxmem=_MAXMEM
    )
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    """Проверяет пароль против хэша любого из поддерживаемых видов."""
    if stored.startswith("$argon2"):
        if _ARGON2 is None:
            # Хэш argon2 есть, а проверить нечем: пускать нельзя.
            log.error("в базе argon2-хэш, но argon2-cffi не установлен")
            return False
        try:
            return _ARGON2.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False
    return _verify_scrypt(password, stored)


def _verify_scrypt(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        actual = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    """
    Пора ли пересчитать хэш при следующем успешном входе.

    Пароль в этот момент есть открытым текстом ровно один раз за всю его
    жизнь — другого повода перевести старый scrypt на argon2id не будет.
    """
    if _ARGON2 is None:
        return False
    if not stored.startswith("$argon2"):
        return True
    try:
        return _ARGON2.check_needs_rehash(stored)
    except InvalidHashError:
        return True


def new_token() -> str:
    """Токен для приложения. 32 байта — угадать нельзя."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """
    В базе лежит только хэш. Токен уже случайный и длинный, поэтому
    медленная функция здесь не нужна — достаточно sha256.
    """
    return hashlib.sha256(token.encode()).hexdigest()


# --- адрес клиента ------------------------------------------------------------

# Самая длинная запись адреса — IPv4-mapped IPv6 вида
# `0000:...:0000:255.255.255.255`, это 45 символов. Длиннее приходит только
# подделка, а колонки под адрес — String(64) (Session.ip, Order.ip), и на
# PostgreSQL длинное значение роняет вставку, то есть вход и заказ отвечают
# 500 на один лишний заголовок.
_IP_MAX_LEN = 45


def _clean_ip(value: str | None) -> str | None:
    """Адрес или ничего: строку неизвестного вида в базу класть нельзя."""
    if not value:
        return None
    # Zone id (`fe80::1%eth0`) ipaddress принимает и никак не ограничивает по
    # длине — с ним проверка формата перестаёт ограничивать длину.
    value = value.strip().split("%", 1)[0]
    if not value or len(value) > _IP_MAX_LEN:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def client_ip(request: Request) -> str | None:
    """
    Адрес клиента — единственный источник на всё приложение.

    Берём ПОСЛЕДНЕЕ значение `X-Forwarded-For`, а не первое. nginx перед
    панелью собирает заголовок через `$proxy_add_x_forwarded_for`: он
    дописывает адрес своего соединения к тому, что прислал клиент. Первое
    значение поэтому пишет сам клиент — подставляя в каждый запрос случайный
    адрес, он заводит новую строку счётчика и обнуляет любое ограничение по
    IP. Последнее значение ставит nginx, и подделать его нельзя.

    Заголовка нет (панель дёрнули напрямую) — остаётся адрес соединения.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        nearest = _clean_ip(forwarded.rsplit(",", 1)[-1])
        if nearest:
            return nearest
    return _clean_ip(request.client.host if request.client else None)
