from __future__ import annotations

import ipaddress
import json
import logging
from typing import TYPE_CHECKING

import httpx

from ..config import settings
from .base import (
    KIND_CANCELED,
    KIND_REFUNDED,
    KIND_SUCCEEDED,
    PaymentError,
    PaymentSession,
    WebhookEvent,
    WebhookRejected,
    amount_to_kopecks,
    kopecks_to_amount,
)

if TYPE_CHECKING:
    from ..models import Order

log = logging.getLogger("panel.payments.yookassa")

API = "https://api.yookassa.ru/v3"
TIMEOUT = 20.0


def _ip_allowed(client_ip: str | None) -> bool:
    networks = settings().yookassa_ips
    if not networks:
        return True
    if not client_ip:
        return False
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in networks:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


class YooKassaProvider:
    name = "yookassa"

    def __init__(self) -> None:
        config = settings()
        self._auth = (config.yookassa_shop_id, config.yookassa_secret_key)
        self._configured = bool(config.yookassa_shop_id and config.yookassa_secret_key)


    def create_payment(self, order: "Order") -> PaymentSession:
        if not self._configured:
            raise PaymentError("ЮKassa не настроена: нет shop_id или секретного ключа")

        return_url = f"{settings().site_url.rstrip('/')}/success.html?order={order.id}"
        body = {
            "amount": {"value": kopecks_to_amount(order.amount_kopecks), "currency": order.currency},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": f"Prosto · тариф {order.plan_code} · заказ {order.id[:8]}",
            "metadata": {"order_id": order.id},
        }
        try:
            response = httpx.post(
                f"{API}/payments",
                json=body,
                auth=self._auth,
                headers={"Idempotence-Key": order.id},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise PaymentError(f"ЮKassa недоступна: {exc}") from exc

        if response.status_code >= 400:
            log.error("ЮKassa отказала: %s %s", response.status_code, response.text[:500])
            raise PaymentError("ЮKassa не приняла платёж")

        data = response.json()
        url = (data.get("confirmation") or {}).get("confirmation_url")
        if not url:
            raise PaymentError("ЮKassa не вернула ссылку на оплату")
        return PaymentSession(payment_id=data["id"], redirect_url=url)


    def verify_webhook(
        self, headers: dict[str, str], raw_body: bytes, client_ip: str | None = None
    ) -> WebhookEvent:
        if not _ip_allowed(client_ip):
            raise WebhookRejected(f"адрес {client_ip} не из списка ЮKassa")

        try:
            payload = json.loads(raw_body.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise WebhookRejected("тело уведомления не разбирается") from exc

        obj = payload.get("object") or {}
        payment_id = obj.get("id")
        if not payment_id:
            raise WebhookRejected("в уведомлении нет идентификатора платежа")

        event_name = str(payload.get("event", ""))
        kind = {
            "payment.succeeded": KIND_SUCCEEDED,
            "payment.canceled": KIND_CANCELED,
            "refund.succeeded": KIND_REFUNDED,
        }.get(event_name)
        if kind is None:
            raise WebhookRejected(f"неизвестное событие {event_name!r}")

        if kind == KIND_REFUNDED:
            payment_id = obj.get("payment_id") or payment_id

        amount = obj.get("amount") or {}
        currency = amount.get("currency", "RUB")
        try:
            kopecks = amount_to_kopecks(amount["value"]) if "value" in amount else None
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise WebhookRejected("сумма в уведомлении не разбирается") from exc
        order_id = (obj.get("metadata") or {}).get("order_id")

        if not self._configured:
            raise WebhookRejected("ключи ЮKassa не заданы, подтвердить платёж нечем")

        confirmed = self._fetch_payment(payment_id)
        if confirmed is not None:
            api_amount = confirmed.get("amount") or {}
            if "value" in api_amount:
                kopecks = amount_to_kopecks(api_amount["value"])
                currency = api_amount.get("currency", currency)
            order_id = (confirmed.get("metadata") or {}).get("order_id") or order_id
            if kind == KIND_SUCCEEDED and confirmed.get("status") != "succeeded":
                raise WebhookRejected(
                    f"уведомление говорит «оплачено», API — {confirmed.get('status')!r}"
                )
        else:
            raise WebhookRejected("не удалось подтвердить платёж через API ЮKassa")

        return WebhookEvent(
            event_id=f"{payment_id}:{event_name}",
            kind=kind,
            provider=self.name,
            order_id=order_id,
            payment_id=payment_id,
            amount_kopecks=kopecks,
            currency=currency,
            raw=payload,
        )

    def _fetch_payment(self, payment_id: str) -> dict | None:
        try:
            response = httpx.get(f"{API}/payments/{payment_id}", auth=self._auth, timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            log.error("не удалось перепроверить платёж %s: %s", payment_id, exc)
            return None
        if response.status_code >= 400:
            log.error("ЮKassa вернула %s на проверку платежа %s", response.status_code, payment_id)
            return None
        return response.json()
