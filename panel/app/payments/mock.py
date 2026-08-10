"""
Провайдер-имитация: весь путь оплаты проходится без единого рубля.

Нужен для двух вещей. Первая — разработка и тесты: сценарий «заказ →
платёжная форма → вебхук → выдача учётки» должен проверяться локально,
включая двадцать повторных доставок одного события. Вторая — витрина: пока
договор с настоящим провайдером не подписан, сайт должен работать целиком,
а не упираться в заглушку.

Уведомление подписывается так же, как у настоящего провайдера — HMAC от
сырого тела. Это не защита (секрет наш собственный), а гарантия, что
боевой код проверки подписи выполняется на каждом прогоне и не сгниёт
незамеченным до дня подключения ЮKassa.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from typing import TYPE_CHECKING
from urllib.parse import quote

from ..config import settings
from .base import (
    KIND_REFUNDED,
    KIND_SUCCEEDED,
    PaymentSession,
    WebhookEvent,
    WebhookRejected,
    amount_to_kopecks,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..models import Order

log = logging.getLogger("panel.payments.mock")

SIGNATURE_HEADER = "x-mock-signature"


def sign(raw_body: bytes) -> str:
    return hmac.new(settings().mock_secret.encode(), raw_body, hashlib.sha256).hexdigest()


class MockProvider:
    """Платёж «как будто»: форма своя, подтверждение по кнопке."""

    name = "mock"

    def create_payment(self, order: "Order") -> PaymentSession:
        payment_id = f"mock-{order.id}"
        # Своя же страница вместо чужой платёжной формы. Карточных полей на
        # ней нет и быть не должно: это витрина, а не приём платежей.
        url = f"{settings().site_url.rstrip('/')}/pay.html?order={quote(order.id)}"
        return PaymentSession(payment_id=payment_id, redirect_url=url)

    def verify_webhook(
        self, headers: dict[str, str], raw_body: bytes, client_ip: str | None = None
    ) -> WebhookEvent:
        provided = headers.get(SIGNATURE_HEADER, "")
        if not provided or not hmac.compare_digest(provided, sign(raw_body)):
            raise WebhookRejected("подпись не совпала")

        payload = json.loads(raw_body.decode())
        kind = KIND_REFUNDED if payload.get("event") == "refund" else KIND_SUCCEEDED
        return WebhookEvent(
            event_id=str(payload["event_id"]),
            kind=kind,
            provider=self.name,
            order_id=payload.get("order_id"),
            payment_id=payload.get("payment_id"),
            amount_kopecks=amount_to_kopecks(payload["amount"]) if "amount" in payload else None,
            currency=payload.get("currency", "RUB"),
            raw=payload,
        )


# --- отправка уведомления самому себе -----------------------------------------


def build_payload(order: "Order", event: str = "succeeded", attempt: int = 1) -> bytes:
    """
    Тело уведомления.

    `event_id` не зависит от номера попытки — в этом весь смысл: повтор
    доставки обязан прийти с тем же идентификатором, иначе идемпотентность
    проверялась бы на данных, которых в жизни не бывает.
    """
    payload = {
        "event_id": f"{order.id}:{event}",
        "event": event,
        "order_id": order.id,
        "payment_id": order.provider_payment_id or f"mock-{order.id}",
        "amount": f"{order.amount_kopecks / 100:.2f}",
        "currency": order.currency,
        "attempt": attempt,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def dispatch(order_id: str, event: str = "succeeded", delay: float | None = None) -> None:
    """
    Отправляет уведомление о себе — в том же процессе, но тем же путём.

    Не через HTTP на самого себя: сетевой круг добавил бы к имитации
    зависимость от того, на каком адресе и порту поднят uvicorn, и упал бы
    за прокси. Вызываем ту же функцию, что и HTTP-обработчик, вместе с
    проверкой подписи и записью в billing_events — проверяется ровно тот
    код, который потом будет обрабатывать настоящую ЮKassa.
    """
    pause = settings().mock_delay_seconds if delay is None else delay

    def worker() -> None:
        if pause > 0:
            time.sleep(pause)
        from ..db import SessionLocal
        from ..models import Order
        from ..services import billing_webhook

        with SessionLocal() as db:
            order = db.get(Order, order_id)
            if order is None:
                log.warning("имитация оплаты: заказ %s исчез", order_id)
                return
            body = build_payload(order, event)
            try:
                billing_webhook.handle(
                    db,
                    provider_name="mock",
                    headers={SIGNATURE_HEADER: sign(body)},
                    raw_body=body,
                    client_ip="127.0.0.1",
                )
            except Exception:  # pragma: no cover - имитация не должна ронять сервис
                log.exception("имитация оплаты не прошла")

    threading.Thread(target=worker, name=f"mock-pay-{order_id[:8]}", daemon=True).start()
