"""
Одноразовые коды TOTP (RFC 6238) для входа в админку — без внешних
зависимостей: HMAC-SHA1, шаг 30 секунд, шесть цифр, как в Google
Authenticator, Aegis, 1Password и прочих.

Секрет хранится в базе только под шифром (crypto.encrypt) — утечка базы
без PANEL_SECRETS_KEY второй фактор не раскрывает. Использованный шаг
запоминается: один и тот же код второй раз не проходит.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

ISSUER = "Prosto VPN"
STEP_SECONDS = 30
DIGITS = 6
# Допуск ±1 шаг: часы телефона и сервера расходятся на десятки секунд.
WINDOW = 1


def generate_secret() -> str:
    """160 бит случайности в base32 без «=» — так его принимают приложения."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    cleaned = secret.strip().replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**DIGITS)).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def verify(secret: str, code: str | None, now: float | None = None) -> int | None:
    """Номер шага, которому соответствует код, или None. Сравнение постоянное по времени."""
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(digits) != DIGITS:
        return None
    base = current_step(now)
    for delta in range(-WINDOW, WINDOW + 1):
        step = base + delta
        if hmac.compare_digest(code_at(secret, step), digits):
            return step
    return None


def otpauth_uri(login: str, secret: str, issuer: str = ISSUER) -> str:
    label = urllib.parse.quote(f"{issuer}:{login}", safe=":")
    query = urllib.parse.urlencode(
        {"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": STEP_SECONDS}
    )
    return f"otpauth://totp/{label}?{query}"
