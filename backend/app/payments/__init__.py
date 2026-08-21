"""
Реестр платёжных провайдеров.

Активный выбирается настройкой `PANEL_PAYMENT_PROVIDER`, но получить по
имени можно любого: вебхуки от прежнего провайдера продолжают приходить
неделями после переключения, и обрабатывать их надо тем кодом, который их
понимает, а не текущим.
"""

from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import (
    KIND_CANCELED,
    KIND_REFUNDED,
    KIND_SUCCEEDED,
    PaymentError,
    PaymentProvider,
    PaymentSession,
    WebhookEvent,
    WebhookRejected,
    amount_to_kopecks,
    kopecks_to_amount,
)
from .cryptocloud import CryptoCloudProvider
from .mock import MockProvider
from .platega import PlategaProvider
from .yookassa import YooKassaProvider

_FACTORIES = {
    MockProvider.name: MockProvider,
    YooKassaProvider.name: YooKassaProvider,
    CryptoCloudProvider.name: CryptoCloudProvider,
    PlategaProvider.name: PlategaProvider,
}

KNOWN = tuple(_FACTORIES)


class UnknownProvider(LookupError):
    pass


@lru_cache(maxsize=None)
def _instance(name: str) -> PaymentProvider:
    factory = _FACTORIES.get(name)
    if factory is None:
        raise UnknownProvider(f"провайдер оплаты {name!r} не поддерживается")
    return factory()


def get(name: str) -> PaymentProvider:
    """
    Провайдер по имени. Экземпляр один: внутри только настройки.

    Единственное исключение из «получить можно любого» — имитация. Её
    уведомления подписаны нашим же секретом, то есть на боевом магазине
    вебхук /mock — это раздача подписок любому, кто угадал секрет. Запрет
    здесь, а не в маршруте: так же закрываются и все прочие вызовы.
    Проверка вне кэша, иначе первый успешный вызов запомнил бы разрешение.
    """
    if name == MockProvider.name and settings().payment_provider != MockProvider.name:
        raise UnknownProvider("имитация оплаты выключена: активен другой провайдер")
    return _instance(name)


def active() -> PaymentProvider:
    return get(settings().payment_provider)


def active_name() -> str:
    return settings().payment_provider


__all__ = [
    "KNOWN",
    "KIND_CANCELED",
    "KIND_REFUNDED",
    "KIND_SUCCEEDED",
    "CryptoCloudProvider",
    "MockProvider",
    "PlategaProvider",
    "PaymentError",
    "PaymentProvider",
    "PaymentSession",
    "UnknownProvider",
    "WebhookEvent",
    "WebhookRejected",
    "YooKassaProvider",
    "active",
    "active_name",
    "amount_to_kopecks",
    "get",
    "kopecks_to_amount",
]
