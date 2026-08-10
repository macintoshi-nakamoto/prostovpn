"""
Обратимое шифрование пароля пользователя.

Зачем оно вообще нужно. Пароль клиента хранится хэшем — из него ничего не
достать, и это правильно. Но человек теряет письмо и звонит в поддержку, а
сбрасывать пароль каждому позвонившему значит разлогинивать его на всех
устройствах ради того, что он и так имел право узнать. Поэтому рядом с
хэшем лежит шифротекст: администратор нажимает «показать», панель
расшифровывает и пишет в журнал, кто и чей пароль посмотрел.

Хэш при этом остаётся главным: вход проверяется по нему, а не по
расшифровке. Утечка базы без `SECRETS_KEY` не отдаёт паролей.

AES-256-GCM: шифрование и проверка целостности одним примитивом, подмена
шифротекста не проходит молча. Nonce — 12 случайных байт на каждую запись,
он же лежит в начале блоба. Формат: `pv1.<base64url(nonce||ciphertext)>`.
Префикс версии оставлен на случай смены схемы: расшифровщик увидит чужой
формат и скажет об этом, а не выдаст мусор.
"""

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
    """Ключа шифрования нет или он не тот — расшифровать нечем."""


def _key() -> bytes:
    """
    Ключ AES из `PANEL_SECRETS_KEY`.

    Строку из окружения приводим к 32 байтам через SHA-256: администратор
    пишет в `.env` человеческую строку, а не ровно 32 байта в base64, и
    требовать от него точной длины — верный способ получить в проде
    «ключ подлиннее, чтоб наверняка».
    """
    raw = settings().secrets_key.strip()
    if not raw:
        raise SecretsUnavailable("PANEL_SECRETS_KEY не задан")
    return hashlib.sha256(raw.encode()).digest()


def available() -> bool:
    """Можно ли вообще шифровать: ключ задан и не оставлен дефолтным."""
    value = settings().secrets_key.strip()
    return bool(value) and value != INSECURE_DEFAULT_SECRET


def encrypt(plaintext: str) -> str:
    """Шифрует строку. Один и тот же текст даёт разный шифротекст."""
    import secrets as _secrets

    nonce = _secrets.token_bytes(_NONCE_LEN)
    blob = nonce + AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return _PREFIX + base64.urlsafe_b64encode(blob).decode()


def decrypt(token: str) -> str:
    """Расшифровывает то, что вернул `encrypt`."""
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
        # Либо сменили PANEL_SECRETS_KEY, либо в базу залезли руками.
        raise SecretsUnavailable("ключ не подходит к этому шифротексту") from exc


def encrypt_or_none(plaintext: str | None) -> str | None:
    """
    Шифрует, но не роняет вызывающего, если ключа нет.

    Создание пользователя не должно падать из-за незаполненного `.env`:
    учётка нужнее, чем возможность посмотреть пароль потом. В журнал при
    этом уходит предупреждение — сам пароль в него, разумеется, не попадает.
    """
    if plaintext is None:
        return None
    try:
        return encrypt(plaintext)
    except SecretsUnavailable as exc:
        log.warning("пароль не зашифрован: %s", exc)
        return None
