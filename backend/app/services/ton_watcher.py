from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import Order, OrderStatus
from ..payments.base import KIND_SUCCEEDED, WebhookEvent
from ..payments.ton import NANO, expected_nanotons
from . import billing_webhook

log = logging.getLogger("panel.ton_watcher")

TIMEOUT = 15.0
BATCH = 50

# Кошелёк шлёт ровно сумму из ссылки, но сеть может удержать копейку
# комиссии на стороне отправителя-контракта — полпроцента прощаем.
TOLERANCE = 0.995


def _pending(db: OrmSession) -> dict[str, Order]:
    rows = db.scalars(
        select(Order).where(
            Order.status == OrderStatus.PENDING.value,
            Order.provider == "ton",
        )
    )
    # Свежие заказы узнаём по комментарию-HMAC, старые (выписаны до
    # перехода) — по номеру; те доживают свои сутки и исчезают.
    from ..payments.ton import order_memo

    pending: dict[str, Order] = {}
    for order in rows:
        pending[order_memo(order)] = order
        pending[order.id] = order
    return pending


def _transactions(address: str) -> list[dict]:
    config = settings()
    headers = {}
    if config.ton_api_key:
        headers["X-API-Key"] = config.ton_api_key
    response = httpx.get(
        f"{config.ton_api_url.rstrip('/')}/getTransactions",
        params={"address": address, "limit": BATCH},
        headers=headers,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"toncenter: {payload.get('error') or payload}")
    return payload.get("result") or []


def run_once(db: OrmSession) -> int:
    """Свести входящие переводы кошелька с ожидающими TON-заказами."""
    address = settings().ton_wallet_address.strip()
    if not address:
        return 0

    pending = _pending(db)
    if not pending:
        return 0

    try:
        transactions = _transactions(address)
    except Exception as exc:
        log.warning("toncenter недоступен (%s) — вернёмся в следующий круг", exc)
        return 0

    done = 0
    for tx in transactions:
        message = tx.get("in_msg") or {}
        comment = (message.get("message") or "").strip()
        order = pending.get(comment)
        if order is None:
            continue

        tx_hash = (tx.get("transaction_id") or {}).get("hash") or ""
        if not tx_hash:
            continue

        try:
            nanotons = int(message.get("value") or 0)
        except (TypeError, ValueError):
            continue

        expected = expected_nanotons(order)
        if not expected:
            log.error("заказ %s: в ссылке оплаты нет суммы — пропускаем", order.id)
            continue

        # Пайплайн вебхуков сверяет рубли, а платёж пришёл в TON. Сверку в
        # тонах делаем здесь: хватило — подтверждаем цену заказа целиком,
        # недоплата — отдаём пропорцию, и общий код честно завалит заказ.
        if nanotons >= expected * TOLERANCE:
            kopecks = order.amount_kopecks
        else:
            kopecks = order.amount_kopecks * nanotons // expected

        event = WebhookEvent(
            event_id=f"ton:{tx_hash}",
            kind=KIND_SUCCEEDED,
            provider="ton",
            order_id=order.id,
            payment_id=tx_hash,
            amount_kopecks=kopecks,
            currency=order.currency,
            raw={
                "nanotons": nanotons,
                "expected_nanotons": expected,
                "ton": f"{nanotons / NANO:.9f}",
                "utime": tx.get("utime"),
                "source": message.get("source"),
            },
        )
        result = billing_webhook.apply_event(db, event)
        if result.result == billing_webhook.OK:
            done += 1
            log.info("заказ %s оплачен в TON: %.4f", order.id, nanotons / NANO)
    return done
