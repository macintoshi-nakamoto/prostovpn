from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..models import Order


class PaymentError(RuntimeError):
    pass


class WebhookRejected(Exception):
    pass


KIND_SUCCEEDED = "payment.succeeded"
KIND_CANCELED = "payment.canceled"
KIND_REFUNDED = "payment.refunded"


@dataclass(slots=True)
class PaymentSession:

    payment_id: str
    redirect_url: str
    expires_at: dt.datetime | None = None


@dataclass(slots=True)
class WebhookEvent:

    event_id: str
    kind: str
    provider: str
    order_id: str | None = None
    payment_id: str | None = None
    amount_kopecks: int | None = None
    currency: str = "RUB"
    raw: dict = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.kind == KIND_SUCCEEDED

    @property
    def is_refund(self) -> bool:
        return self.kind == KIND_REFUNDED


@runtime_checkable
class PaymentProvider(Protocol):

    name: str

    def create_payment(self, order: "Order") -> PaymentSession:
        ...

    def verify_webhook(
        self, headers: dict[str, str], raw_body: bytes, client_ip: str | None = None
    ) -> WebhookEvent:
        ...


def kopecks_to_amount(kopecks: int) -> str:
    return f"{Decimal(kopecks) / 100:.2f}"


def amount_to_kopecks(value: str | float | Decimal) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal(1)))
