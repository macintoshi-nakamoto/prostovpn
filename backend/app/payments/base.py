"""
Общий интерфейс платёжного провайдера.

Провайдера меняют: один перестаёт принимать карты, второй просит комиссию
выше, третий нужен для крипты параллельно с первым. Поэтому всё, что знает
о конкретном API, живёт в одном классе на провайдера, а остальная система
разговаривает с ним двумя методами: «создай платёж» и «проверь, что это
уведомление действительно от тебя».

Разбор уведомления намеренно возвращает `WebhookEvent`, а не сырой JSON.
Ядро выдачи не должно знать, что у ЮKassa сумма лежит в `object.amount.value`
строкой в рублях, а у CryptoCloud её в уведомлении нет вовсе.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from ..models import Order


class PaymentError(RuntimeError):
    """Провайдер не смог создать платёж — человеку нужно показать ошибку."""


class WebhookRejected(Exception):
    """
    Уведомление не прошло проверку подлинности.

    Отдельный тип, потому что реакция на него особая: 403 и запись в лог,
    без единой попытки что-то из тела разобрать.
    """


# Что произошло с платежом. Строки, а не enum провайдера: у каждого свои
# названия событий, и приводим их к этим трём здесь же, при разборе.
KIND_SUCCEEDED = "payment.succeeded"
KIND_CANCELED = "payment.canceled"
KIND_REFUNDED = "payment.refunded"


@dataclass(slots=True)
class PaymentSession:
    """Куда отправить человека платить."""

    payment_id: str
    redirect_url: str
    # Когда ссылка протухнет (наивный UTC). None — провайдер не сообщил;
    # вызывающий тогда оценивает свежесть по времени создания заказа.
    expires_at: dt.datetime | None = None


@dataclass(slots=True)
class WebhookEvent:
    """
    Разобранное уведомление провайдера.

    `event_id` — ключ идемпотентности. Он обязан быть устойчивым: провайдер
    повторяет доставку того же события, и идентификатор при повторе должен
    совпадать до символа, иначе повтор станет вторым событием и второй
    учёткой. Где у провайдера нет идентификатора события, собираем его из
    идентификатора платежа и вида события — этого достаточно.

    `amount_kopecks = None` означает «в уведомлении суммы нет и получить её
    не удалось». Такое бывает у криптоплатежей: в колбэке приходит сумма в
    монете, а не в рублях. Ядро выдачи разбирает этот случай отдельно.
    """

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
    """Минимум, который обязан уметь провайдер."""

    name: str

    def create_payment(self, order: "Order") -> PaymentSession:
        """Регистрирует платёж и возвращает ссылку на форму оплаты."""
        ...

    def verify_webhook(
        self, headers: dict[str, str], raw_body: bytes, client_ip: str | None = None
    ) -> WebhookEvent:
        """
        Проверяет подлинность и разбирает уведомление.

        Проверка идёт до разбора тела: подписанное тело сначала сверяют, а
        потом читают. Не прошло — `WebhookRejected`.
        """
        ...


def kopecks_to_amount(kopecks: int) -> str:
    """Копейки в строку «300.00», как её ждут платёжные API."""
    return f"{Decimal(kopecks) / 100:.2f}"


def amount_to_kopecks(value: str | float | Decimal) -> int:
    """
    Строку «300.00» обратно в копейки.

    Через Decimal, а не float: 3.10 в двоичной плавающей точке — это
    3.0999999999999996, и умножение на сто даёт 309 копеек вместо 310.
    """
    return int((Decimal(str(value)) * 100).quantize(Decimal(1)))
