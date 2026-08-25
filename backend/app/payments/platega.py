from __future__ import annotations

import datetime as dt
import hmac
import json
import logging
from typing import TYPE_CHECKING, Any

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
)

if TYPE_CHECKING:
    from ..models import Order

log = logging.getLogger("panel.payments.platega")

TIMEOUT = 20.0

_KINDS = {
    "CONFIRMED": KIND_SUCCEEDED,
    "CANCELED": KIND_CANCELED,
    "CHARGEBACKED": KIND_REFUNDED,
}

SUBSCRIPTION_METHOD = 6

METHODS = {
    "sbp": 2,
    "card": 11,
    "crypto": 13,
    "sberpay": 14,
}


def method_code(name: str | None) -> int:
    if name:
        code = METHODS.get(name)
        if code is not None:
            return code
        log.warning("неизвестный способ оплаты %r, беру метод из настроек", name)
    return settings().platega_payment_method


def _base_url() -> str:
    return settings().platega_api_url.rstrip("/")


def _auth_headers() -> dict[str, str]:
    config = settings()
    return {
        "X-MerchantId": config.platega_merchant_id,
        "X-Secret": config.platega_secret,
    }


def configured() -> bool:
    config = settings()
    return bool(config.platega_merchant_id and config.platega_secret)


def authenticate(headers: dict[str, str]) -> None:
    config = settings()
    if not config.platega_merchant_id or not config.platega_secret:
        raise WebhookRejected("Platega не настроена: нет merchant id или секрета")

    merchant = headers.get("x-merchantid", "")
    secret = headers.get("x-secret", "")
    merchant_ok = hmac.compare_digest(merchant, config.platega_merchant_id)
    secret_ok = hmac.compare_digest(secret, config.platega_secret)
    if not (merchant_ok and secret_ok):
        raise WebhookRejected("заголовки X-MerchantId/X-Secret не совпали с настройками")


def parse_body(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body.decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebhookRejected("тело уведомления не разбирается") from exc
    if not isinstance(payload, dict):
        raise WebhookRejected("тело уведомления не объект")
    return {str(key).lower(): value for key, value in payload.items()}


def is_subscription_event(raw_body: bytes) -> bool:
    try:
        payload = parse_body(raw_body)
    except WebhookRejected:
        return False
    if payload.get("subscriptionid"):
        return True
    status = str(payload.get("status", ""))
    return status.startswith("SUBSCRIPTION_")


def api_request(method: str, path: str, body: dict | None = None) -> dict:
    if not configured():
        raise PaymentError("Platega не настроена: нет merchant id или секрета")

    url = f"{_base_url()}{path}"
    try:
        response = httpx.request(
            method, url, json=body, headers=_auth_headers(), timeout=TIMEOUT
        )
    except httpx.HTTPError as exc:
        raise PaymentError(f"Platega недоступна: {exc}") from exc

    if response.status_code >= 400:
        log.error("Platega ответила %s на %s %s: %s", response.status_code, method, path, response.text[:500])
        error = PaymentError(f"Platega отказала ({response.status_code})")
        error.body = response.text[:300]
        raise error

    try:
        data = response.json()
    except ValueError as exc:
        raise PaymentError("Platega вернула не-JSON") from exc
    if not isinstance(data, dict):
        raise PaymentError("Platega вернула неожиданный ответ")
    return data


class PlategaProvider:
    name = "platega"


    def create_payment(self, order: "Order") -> PaymentSession:
        config = settings()
        site = config.site_url.rstrip("/")

        if getattr(order, "origin", "site") == "bot" and config.telegram_bot_username:
            success_url = f"https://t.me/{config.telegram_bot_username}"
            failed_url = success_url
        else:
            success_url = f"{site}/account?order={order.id}"
            failed_url = f"{site}/account?order={order.id}&failed=1"

        body = {
            "paymentMethod": method_code(getattr(order, "payment_method", None)),
            "paymentDetails": {
                "amount": order.amount_kopecks / 100,
                "currency": order.currency,
            },
            "description": f"Prosto · тариф {order.plan_code} · заказ {order.id[:8]}",
            "return": success_url,
            "failedUrl": failed_url,
            "payload": order.id,
            "metadata": {
                "userId": str(order.user_id) if order.user_id else order.email,
            },
        }

        data = api_request("POST", "/transaction/process", body)
        transaction_id = data.get("transactionId")
        redirect = data.get("redirect") or data.get("url")
        if not transaction_id or not redirect:
            log.error("Platega не вернула transactionId/redirect: %s", data)
            raise PaymentError("Platega не вернула ссылку на оплату")
        return PaymentSession(
            payment_id=str(transaction_id),
            redirect_url=str(redirect),
            expires_at=_link_deadline(data.get("expiresIn")),
        )


    def verify_webhook(
        self, headers: dict[str, str], raw_body: bytes, client_ip: str | None = None
    ) -> WebhookEvent:
        authenticate(headers)
        payload = parse_body(raw_body)

        if is_subscription_event(raw_body):
            raise WebhookRejected("событие подписки пришло в обработчик разовых платежей")

        payment_id = str(payload.get("id") or "")
        if not payment_id:
            raise WebhookRejected("в уведомлении нет идентификатора транзакции")

        status_name = str(payload.get("status") or "")
        kind = _KINDS.get(status_name)
        if kind is None:
            raise WebhookRejected(f"неизвестный статус {status_name!r}")

        currency = str(payload.get("currency") or "RUB")
        kopecks: int | None
        try:
            kopecks = amount_to_kopecks(payload["amount"]) if "amount" in payload else None
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise WebhookRejected("сумма в уведомлении не разбирается") from exc

        order_id = payload.get("payload") or None
        if order_id is not None:
            order_id = str(order_id) or None

        if kind == KIND_SUCCEEDED:
            confirmed = self._fetch_transaction(payment_id)
            if confirmed is None:
                log.error("платёж %s: API Platega недоступно, сумма не подтверждена", payment_id)
                kopecks = None
            else:
                api_status = str(confirmed.get("status") or "")
                if api_status != "CONFIRMED":
                    raise WebhookRejected(
                        f"уведомление говорит «оплачено», API — {api_status!r}"
                    )
                details = confirmed.get("paymentDetails") or {}
                if isinstance(details, dict) and "amount" in details:
                    try:
                        kopecks = amount_to_kopecks(details["amount"])
                        currency = str(details.get("currency") or currency)
                    except (ValueError, TypeError, ArithmeticError):
                        log.error("платёж %s: сумма из API не разбирается: %r", payment_id, details)
                        kopecks = None

        return WebhookEvent(
            event_id=f"{payment_id}:{status_name}",
            kind=kind,
            provider=self.name,
            order_id=order_id,
            payment_id=payment_id,
            amount_kopecks=kopecks,
            currency=currency,
            raw=payload,
        )

    def _fetch_transaction(self, transaction_id: str) -> dict | None:
        try:
            return api_request("GET", f"/transaction/{transaction_id}")
        except PaymentError as exc:
            log.error("не удалось перепроверить транзакцию %s: %s", transaction_id, exc)
            return None


def _link_deadline(expires_in: object) -> dt.datetime | None:
    if not isinstance(expires_in, str) or expires_in.count(":") != 2:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in expires_in.split(":"))
    except ValueError:
        return None
    delta = dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)
    if delta <= dt.timedelta(0):
        return None
    from ..models import utcnow

    return utcnow() + delta
