"""
Пароли и токены.

Хэширование — scrypt из стандартной библиотеки: не тянет за собой сборку
нативных пакетов и настроен по рекомендациям OWASP. Сравнение всегда
постоянного времени, иначе по времени ответа подбирается хэш.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

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
    salt = secrets.token_bytes(_SALT_LEN)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DK_LEN, maxmem=_MAXMEM
    )
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


def verify_password(password: str, stored: str) -> bool:
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


def new_token() -> str:
    """Токен для приложения. 32 байта — угадать нельзя."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """
    В базе лежит только хэш. Токен уже случайный и длинный, поэтому
    медленная функция здесь не нужна — достаточно sha256.
    """
    return hashlib.sha256(token.encode()).hexdigest()
