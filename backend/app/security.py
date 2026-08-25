from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import secrets

from fastapi import Request

log = logging.getLogger("panel.security")

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError
    from argon2.low_level import Type as _Argon2Type

    _ARGON2 = PasswordHasher(
        time_cost=3, memory_cost=64 * 1024, parallelism=1, hash_len=32, salt_len=16,
        type=_Argon2Type.ID,
    )
except Exception:
    _ARGON2 = None
    InvalidHashError = VerificationError = Exception
    log.warning(
        "argon2-cffi недоступен, пароли хэшируются scrypt. "
        "Поставьте пакет из requirements.txt на боевом сервере."
    )

_N = 2 ** 15
_R = 8
_P = 1
_DK_LEN = 32
_SALT_LEN = 16

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
    if stored.startswith("$argon2"):
        if _ARGON2 is None:
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
    if _ARGON2 is None:
        return False
    if not stored.startswith("$argon2"):
        return True
    try:
        return _ARGON2.check_needs_rehash(stored)
    except InvalidHashError:
        return True


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_RATE_SALT = secrets.token_bytes(32)


def ip_tag(ip: str | None) -> str:
    import hmac

    return hmac.new(_RATE_SALT, (ip or "unknown").encode(), hashlib.sha256).hexdigest()[:20]


_IP_MAX_LEN = 45


def _clean_ip(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().split("%", 1)[0]
    if not value or len(value) > _IP_MAX_LEN:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        nearest = _clean_ip(forwarded.rsplit(",", 1)[-1])
        if nearest:
            return nearest
    return _clean_ip(request.client.host if request.client else None)
