"""
CryptoCloud — приём криптовалюты.

Уведомление приходит формой и несёт JWT, подписанный секретом магазина
(HS256). Подпись и есть проверка подлинности: подделать тело, не зная
секрета, нельзя. Проверяем её сами, без pyjwt — алгоритм один, и тащить
зависимость ради тридцати строк незачем.

Отдельная сложность: подписан только сам токен, а поля формы — нет. Их
может переписать любой, у кого оказался годный токен: например повторить
настоящую доставку, подставив чужой `order_id`. Поэтому из уведомления
берётся ровно один идентификатор счёта — из подписанной части, — а статус,
заказ, сумма и валюта запрашиваются у API по этому идентификатору. Форма
годится только для журнала и для сверки с токеном.

Второе следствие: в колбэке нет суммы в рублях, приходит сумма в монете и
её код. Фиатную сумму отдаёт тот же ответ API. Если ответа нет, счёт не
найден или в нём нет фиатных полей — уведомление не принимается, чтобы
CryptoCloud повторил доставку; выдавать доступ по неподтверждённым данным
нельзя.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
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

# Часы у нас и у провайдера расходятся на секунды — на столько же и допуск.
CLOCK_LEEWAY = 60.0

# Статусы счёта, при которых деньги действительно получены.
PAID_STATUSES = {"paid", "overpaid", "success"}


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
        claims = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError) as exc:
        raise WebhookRejected("тело токена не разбирается") from exc

    _check_lifetime(claims)
    return claims


def _check_lifetime(claims: dict) -> None:
    """
    Срок жизни токена.

    Без этой проверки однажды подсмотренный колбэк годен вечно: подпись у
    него настоящая, и повторить его может кто угодно, кому он попался — в
    логах прокси, в истории доставок, в чужом отчёте об ошибке.
    """
    now = time.time()
    exp = claims.get("exp")
    if exp is None:
        raise WebhookRejected("в токене нет срока действия")
    try:
        if float(exp) + CLOCK_LEEWAY < now:
            raise WebhookRejected("срок действия токена истёк")
        for name in ("nbf", "iat"):
            moment = claims.get(name)
            if moment is not None and float(moment) - CLOCK_LEEWAY > now:
                raise WebhookRejected(f"токен помечен будущим временем ({name})")
    except (TypeError, ValueError) as exc:
        raise WebhookRejected("время в токене не разбирается") from exc


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

        # Подписан только токен. Всё, что решает судьбу заказа, берём из
        # него и из ответа API; поля формы на решение не влияют вовсе.
        invoice_id = claims.get("id")
        if not invoice_id:
            raise WebhookRejected("в подписанном токене нет идентификатора счёта")
        invoice_id = str(invoice_id)

        form_invoice = form.get("invoice_id")
        if form_invoice and str(form_invoice) != invoice_id:
            raise WebhookRejected("форма не соответствует подписанному токену")

        invoice = self._fetch_invoice(invoice_id)
        status = str(invoice.get("status", "")).lower()
        kind = KIND_SUCCEEDED if status in PAID_STATUSES else KIND_CANCELED
        kopecks, currency = _fiat_amount(invoice)

        return WebhookEvent(
            # Ключ идемпотентности тоже из подписанного счёта и ответа API:
            # собранный из полей формы, он менялся бы вместе с ними, и
            # реплей с переписанными полями стал бы «новым событием».
            event_id=f"{invoice_id}:{status or 'unknown'}",
            kind=kind,
            provider=self.name,
            order_id=invoice.get("order_id"),
            payment_id=invoice_id,
            amount_kopecks=kopecks,
            currency=currency,
            # Токен из тела не сохраняем: он подписан секретом магазина, и
            # в журнале событий ему делать нечего.
            raw={key: value for key, value in form.items() if key != "token"},
        )

    def _fetch_invoice(self, invoice_id: str) -> dict:
        """
        Счёт из API — единственный источник статуса и суммы.

        Не получилось спросить — уведомление отклоняем, а не принимаем «как
        есть»: провайдер повторит доставку, а выдача по неподтверждённым
        данным необратима.
        """
        if not self._configured:
            raise WebhookRejected("CryptoCloud не настроен, подтвердить счёт нечем")
        try:
            response = httpx.post(
                f"{API}/invoice/merchant/info",
                json={"uuids": [invoice_id]},
                headers=self._headers(),
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as exc:
            log.error("не удалось запросить счёт %s: %s", invoice_id, exc)
            raise WebhookRejected("CryptoCloud недоступен, счёт не подтверждён") from exc
        if response.status_code >= 400:
            log.error("CryptoCloud вернул %s на запрос счёта %s", response.status_code, invoice_id)
            raise WebhookRejected("CryptoCloud не подтвердил счёт")

        result = (response.json() or {}).get("result") or []
        if not result:
            raise WebhookRejected(f"счёт {invoice_id} у CryptoCloud не найден")
        return result[0]


def _fiat_amount(invoice: dict) -> tuple[int | None, str]:
    """
    Фиатная сумма счёта.

    Только явные фиатные поля: `amount` и `currency.code` — это сумма в
    монете и код монеты, и подстановка их вместо рублей отправляла
    оплаченный заказ в `failed` навсегда. Фолбэка на них нет, `or` тоже нет:
    он срабатывает и на нулевой сумме.
    """
    fiat = invoice.get("amount_in_fiat")
    fiat_currency = invoice.get("fiat_currency")
    if fiat is None or not fiat_currency:
        return None, "RUB"
    try:
        return amount_to_kopecks(fiat), str(fiat_currency).upper()
    except (ValueError, TypeError, ArithmeticError):
        # Decimal на мусорном значении бросает InvalidOperation — это
        # ArithmeticError, обычным ValueError его не поймать.
        return None, str(fiat_currency).upper()
