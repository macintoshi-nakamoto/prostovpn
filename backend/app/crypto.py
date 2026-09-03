from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import INSECURE_DEFAULT_SECRET, settings

log = logging.getLogger("panel.crypto")

_PREFIX = "pv1."
_NONCE_LEN = 12


class SecretsUnavailable(RuntimeError):
    pass


def _key() -> bytes:
    raw = settings().secrets_key.strip()
    if not raw:
        raise SecretsUnavailable("PANEL_SECRETS_KEY не задан")
    return hashlib.sha256(raw.encode()).digest()


def available() -> bool:
    value = settings().secrets_key.strip()
    return bool(value) and value != INSECURE_DEFAULT_SECRET


def encrypt(plaintext: str) -> str:
    import secrets as _secrets

    if not available():
        raise SecretsUnavailable("PANEL_SECRETS_KEY не задан или оставлен по умолчанию")

    nonce = _secrets.token_bytes(_NONCE_LEN)
    blob = nonce + AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return _PREFIX + base64.urlsafe_b64encode(blob).decode()


def decrypt(token: str) -> str:
    if not token or not token.startswith(_PREFIX):
        raise SecretsUnavailable("неизвестный формат шифротекста")
    try:
        blob = base64.urlsafe_b64decode(token[len(_PREFIX) :].encode())
    except (ValueError, TypeError) as exc:
        raise SecretsUnavailable("шифротекст повреждён") from exc
    if len(blob) <= _NONCE_LEN:
        raise SecretsUnavailable("шифротекст повреждён")
    try:
        return AESGCM(_key()).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], None).decode()
    except InvalidTag as exc:
        raise SecretsUnavailable("ключ не подходит к этому шифротексту") from exc


def is_encrypted(value: str | None) -> bool:
    """Строка уже прошла через encrypt (по префиксу формата)."""
    return bool(value) and value.startswith(_PREFIX)


def encrypt_or_none(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    try:
        return encrypt(plaintext)
    except SecretsUnavailable as exc:
        log.warning("пароль не зашифрован: %s", exc)
        return None


def blind_index(value: str) -> str:
    import hmac

    key = hashlib.sha256(b"blind-index:" + settings().secrets_key.strip().encode()).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
