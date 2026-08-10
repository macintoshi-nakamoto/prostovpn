"""
CryptoCloud — приём криптовалюты.

Уведомление приходит формой и несёт JWT, подписанный секретом магазина
(HS256). Подпись и есть проверка подлинности: подделать тело, не зная
секрета, нельзя. Проверяем её сами, без pyjwt — алгоритм один, и тащить
зависимость ради тридцати строк незачем.

Отдельная сложность: в колбэке нет суммы в рублях. Приходит сумма в монете
и её код. Сверять с ценой тарифа нечего, поэтому рублёвую сумму
запрашиваем у API по идентификатору счёта. Не получилось — оставляем
`amount_kopecks = None`, и ядро выдачи разбирается с этим само: подпись
проверена, значит источник настоящий, но в журнал события уйдёт пометка,
что сумму подтвердить не удалось.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

import httpx

from ..config import settings
from .base import (
    KIND_CANCELED,
    KIND_SUCCEEDED,
    PaymentError,
    PaymentSession,
    WebhookEvent,
    WebhookRejected,
    amount_to_kopecks,
    kopecks_to_amount,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..models import Order

log = logging.getLogger("panel.payments.cryptocloud")

API = "https://api.cryptocloud.plus/v2"
TIMEOUT = 20.0


def _b64url_decode(segment: str) -> bytes:
    # JWT режет выравнивающие «=» — возвращаем их перед разбором.
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def verify_jwt(token: str, secret: str) -> dict:
    """Проверяет HS256-подпись и возвращает полезную нагрузку."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise WebhookRejected("токен уведомления не похож на JWT") from exc

    try:
        header = json.loads(_b64url_decode(header_b64))
    except (ValueError, TypeError) as exc:
        raise WebhookRejected("заголовок токена не разбирается") from exc

    if header.get("alg") != "HS256":
        # Классическая дыра: принять alg=none и поверить любому телу.
        raise WebhookRejected(f"неожиданный алгоритм подписи {header.get('alg')!r}")

    expected = hmac.new(
        secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256
    ).digest()
    try:
        provided = _b64url_decode(signature_b64)
    except (ValueError, TypeError) as exc:
        raise WebhookRejected("подпись токена не разбирается") from exc

    if not hmac.compare_digest(expected, provided):
        raise WebhookRejected("подпись токена не совпала")

    try:
        return json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError) as exc:
        raise WebhookRejected("тело токена не разбирается") from exc


class CryptoCloudProvider:
    name = "cryptocloud"

    def __init__(self) -> None:
        config = settings()
        self._api_key = config.cryptocloud_api_key
        self._shop_id = config.cryptocloud_shop_id
        self._secret = config.cryptocloud_secret
        self._configured = bool(self._api_key and self._shop_id)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._api_key}"}

    def create_payment(self, order: "Order") -> PaymentSession:
        if not self._configured:
            raise PaymentError("CryptoCloud не настроен: нет ключа API или идентификатора магазина")

        body = {
            "shop_id": self._shop_id,
            "amount": float(kopecks_to_amount(order.amount_kopecks)),
            "currency": order.currency,
            "order_id": order.id,
            "email": order.email,
        }
        try:
            response = httpx.post(
                f"{API}/invoice/create", json=body, headers=self._headers(), timeout=TIMEOUT
            )
        except httpx.HTTPError as exc:
            raise PaymentError(f"CryptoCloud недоступен: {exc}") from exc

        if response.status_code >= 400:
            log.error("CryptoCloud отказал: %s %s", response.status_code, response.text[:500])
            raise PaymentError("CryptoCloud не принял платёж")

        data = response.json()
        if data.get("status") != "success":
            raise PaymentError(f"CryptoCloud вернул статус {data.get('status')!r}")

        result = data.get("result") or {}
        link = result.get("link")
        uuid = result.get("uuid")
        if not link or not uuid:
            raise PaymentError("CryptoCloud не вернул ссылку на оплату")
        return PaymentSession(payment_id=uuid, redirect_url=link)

    def verify_webhook(
        self, headers: dict[str, str], raw_body: bytes, client_ip: str | None = None
    ) -> WebhookEvent:
        if not self._secret:
            # Без секрета проверить подпись невозможно, а принимать
            # непроверенные уведомления об оплате нельзя ни при каких
            # обстоятельствах: это раздача доступа кому угодно.
            raise WebhookRejected("PANEL_CRYPTOCLOUD_SECRET не задан, проверить подпись нечем")

        form = {key: values[0] for key, values in parse_qs(raw_body.decode(), keep_blank_values=True).items()}
        if not form:
            try:
                form = json.loads(raw_body.decode())
            except (ValueError, UnicodeDecodeError) as exc:
                raise WebhookRejected("тело уведомления не разбирается") from exc

        token = form.get("token")
        if not token:
            raise WebhookRejected("в уведомлении нет токена подписи")

        claims = verify_jwt(token, self._secret)

        invoice_id = form.get("invoice_id") or claims.get("id")
        if not invoice_id:
            raise WebhookRejected("в уведомлении нет идентификатора счёта")

        status = str(form.get("status", "")).lower()
        kind = KIND_SUCCEEDED if status in {"success", "paid"} else KIND_CANCELED

        order_id = form.get("order_id") or claims.get("order_id")
        kopecks, currency = self._fiat_amount(invoice_id)

        return WebhookEvent(
            event_id=f"{invoice_id}:{status or 'unknown'}",
            kind=kind,
            provider=self.name,
            order_id=order_id,
            payment_id=invoice_id,
            amount_kopecks=kopecks,
            currency=currency,
            # Токен из тела не сохраняем: он подписан секретом магазина, и
            # в журнале событий ему делать нечего.
            raw={key: value for key, value in form.items() if key != "token"},
        )

    def _fiat_amount(self, invoice_id: str) -> tuple[int | None, str]:
        """Рублёвая сумма счёта из API — в колбэке её нет."""
        if not self._configured:
            return None, "RUB"
        try:
            response = httpx.post(
                f"{API}/invoice/merchant/info",
                json={"uuids": [invoice_id]},
                headers=self._headers(),
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as exc:
            log.error("не удалось запросить счёт %s: %s", invoice_id, exc)
            return None, "RUB"
        if response.status_code >= 400:
            log.error("CryptoCloud вернул %s на запрос счёта %s", response.status_code, invoice_id)
            return None, "RUB"

        result = (response.json() or {}).get("result") or []
        if not result:
            return None, "RUB"
        invoice = result[0]
        fiat = invoice.get("amount_in_fiat") or invoice.get("amount")
        currency = ((invoice.get("currency") or {}).get("code")) or "RUB"
        if fiat is None:
            return None, currency
        try:
            return amount_to_kopecks(fiat), currency
        except (ValueError, TypeError):
            return None, currency
