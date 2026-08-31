from __future__ import annotations

import logging
import math
import threading
import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from ..config import settings
from .base import PaymentError, PaymentSession, WebhookRejected

if TYPE_CHECKING:
    from ..models import Order

log = logging.getLogger("panel.payments.ton")

TIMEOUT = 15.0
RATE_TTL = 300.0
NANO = 1_000_000_000
MIN_NANOTON = 10_000_000  # мельче 0.01 TON счёт не выставляем

_rate_lock = threading.Lock()
_rate_cache: tuple[float, float] | None = None  # (рублей за 1 TON, monotonic)


def _fetch_rate_rub() -> float:
    # CoinGecko отдаёт фиатный курс без ключа; toncenter курсами не занимается.
    response = httpx.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "the-open-network", "vs_currencies": "rub"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    rate = float(response.json()["the-open-network"]["rub"])
    if rate <= 0:
        raise PaymentError("курс TON не положителен")
    return rate


def ton_rate_rub() -> float:
    global _rate_cache
    with _rate_lock:
        now = time.monotonic()
        if _rate_cache and now - _rate_cache[1] < RATE_TTL:
            return _rate_cache[0]
        try:
            rate = _fetch_rate_rub()
        except Exception as exc:
            # Старый курс лучше отказа: спред всё равно страхует от дрейфа.
            if _rate_cache:
                log.warning("курс TON не обновился (%s) — работаем на прежнем", exc)
                return _rate_cache[0]
            raise PaymentError(f"курс TON недоступен: {exc}") from exc
        _rate_cache = (rate, now)
        log.info("курс TON: %.2f ₽", rate)
        return rate


def expected_nanotons(order: "Order") -> int | None:
    """Сумма счёта в нанотонах — из ссылки оплаты, отдельного поля нет."""
    parts = urlsplit(order.redirect_url or "")
    if parts.scheme != "ton":
        return None
    values = parse_qs(parts.query).get("amount")
    try:
        return int(values[0]) if values else None
    except (TypeError, ValueError):
        return None


class TonProvider:
    """Приём TON на кошелёк-кассу: без приватных ключей и вебхуков.

    Счёт — ссылка ton://transfer с адресом, суммой и комментарием-номером
    заказа; фронт превращает её в запрос подписи через TON Connect. Оплату
    подтверждает не вебхук, а вотчер (services/ton_watcher.py): он читает
    входящие транзакции кошелька через toncenter и матчит комментарии.
    """

    name = "ton"

    def create_payment(self, order: "Order") -> PaymentSession:
        config = settings()
        address = config.ton_wallet_address.strip()
        if not address:
            raise PaymentError("кошелёк TON не настроен (PANEL_TON_WALLET_ADDRESS)")
        if order.currency != "RUB":
            raise PaymentError(f"TON принимает рублёвые заказы, а не {order.currency}")

        rubles = order.amount_kopecks / 100
        ton = rubles / ton_rate_rub() * (1 + config.ton_rate_spread)
        nanotons = max(math.ceil(ton * NANO), MIN_NANOTON)

        link = f"ton://transfer/{address}?amount={nanotons}&text={quote(order.id)}"
        log.info("заказ %s: счёт на %.4f TON (%.2f ₽)", order.id, nanotons / NANO, rubles)
        return PaymentSession(payment_id=order.id, redirect_url=link)

    def verify_webhook(
        self, headers: dict[str, str], raw_body: bytes, client_ip: str | None = None
    ):
        raise WebhookRejected("у TON нет вебхуков — оплату подтверждает вотчер")
