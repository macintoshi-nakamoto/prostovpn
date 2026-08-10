"""
Приём уведомлений об оплате.

Единственная точка, где заказ становится оплаченным, а человек получает
доступ. Всё остальное — витрина. Поэтому здесь четыре обязательных рубежа,
и ни один из них не является перестраховкой:

1. **Подлинность до разбора.** Подпись или адрес отправителя проверяются
   раньше, чем тело вообще будет прочитано как JSON. Разбирать чужие данные,
   ещё не зная, чьи они, — это делать работу за того, кто их прислал.

2. **Идемпотентность вставкой.** Провайдеры повторяют доставку, пока не
   увидят 200, а некоторые и после. Проверка «а нет ли уже такого события»
   отдельным SELECT проигрывает гонку двум одновременным доставкам: оба
   запроса не найдут записи и оба выдадут учётку. Побеждает только вставка
   с первичным ключом: вторая доставка получает конфликт и уходит.

3. **Сверка суммы.** Заказ помнит, на какую сумму человек соглашался. Если
   в уведомлении другая — это либо подделка, либо оплата не того заказа;
   в обоих случаях доступ не выдаётся, а заказ уходит в `failed` с
   причиной, видимой администратору.

4. **200 почти всегда.** Как только событие записано, провайдеру отвечают
   успехом. Ошибка нашей обработки — наша проблема, и решается повторной
   попыткой из панели или обходчиком, а не 500-м ответом: на 500 провайдер
   начнёт долбить эндпоинт и может создать дубли на соседних узлах.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .. import payments
from ..models import AuditLog, BillingEvent, Order, OrderStatus, utcnow
from ..payments.base import WebhookEvent
from . import orders as orders_service

log = logging.getLogger("panel.webhook")

# Что записывается в billing_events.result и попадает в админку.
OK = "ok"
DUPLICATE = "duplicate"
UNKNOWN_ORDER = "unknown_order"
AMOUNT_MISMATCH = "amount_mismatch"
AMOUNT_UNVERIFIED = "amount_unverified"
IGNORED = "ignored"
REFUNDED = "refunded"
ERROR = "error"


@dataclass(slots=True)
class WebhookResult:
    """Итог обработки. `http_status` — то, что уходит провайдеру."""

    result: str
    http_status: int = 200
    order_id: str | None = None
    detail: str | None = None


def handle(
    db: OrmSession,
    provider_name: str,
    headers: dict[str, str],
    raw_body: bytes,
    client_ip: str | None,
) -> WebhookResult:
    """Полный путь уведомления. Исключения наружу не выпускает."""
    provider = payments.get(provider_name)  # UnknownProvider ловит вызывающий

    # --- рубеж 1: подлинность -------------------------------------------------
    event = provider.verify_webhook(headers, raw_body, client_ip)

    # --- рубеж 2: идемпотентность ---------------------------------------------
    if not _claim(db, event):
        log.info("повтор события %s от %s — пропущено", event.event_id, provider_name)
        return WebhookResult(DUPLICATE, order_id=event.order_id)

    try:
        result = _process(db, event)
    except Exception as exc:  # ошибки обработки не превращаются в 500
        db.rollback()
        log.exception("обработка события %s провалилась", event.event_id)
        _mark(db, event.event_id, ERROR, str(exc)[:500])
        # 200: событие принято и записано. Заказ остался неоплаченным, его
        # подберёт retry_stuck() или администратор кнопкой «выдать вручную».
        return WebhookResult(ERROR, order_id=event.order_id, detail=str(exc))

    _mark(db, event.event_id, result.result, result.detail)
    return result


# --- идемпотентность ----------------------------------------------------------


def _claim(db: OrmSession, event: WebhookEvent) -> bool:
    """
    Пытается застолбить событие. `False` — такое уже обрабатывали.

    Вставка отдельным коммитом и до всякой работы: если процесс упадёт
    посередине выдачи, повтор доставки не создаст вторую учётку, а придёт
    в _process с уже записанным событием и получит DUPLICATE. Потерянную
    выдачу видно в панели как оплаченное событие при неоплаченном заказе —
    это чинится нажатием кнопки, а вторая учётка не чинится ничем.
    """
    row = {
        "event_id": event.event_id,
        "provider": event.provider,
        "kind": event.kind,
        "order_id": event.order_id,
        "payload": event.raw,
        "received_at": utcnow(),
    }

    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect in {"postgresql", "sqlite"}:
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert

        statement = insert(BillingEvent).values(**row).on_conflict_do_nothing(
            index_elements=[BillingEvent.event_id]
        )
        inserted = db.execute(statement).rowcount
        db.commit()
        return bool(inserted)

    # Прочие СУБД: та же семантика через нарушение первичного ключа.
    try:
        db.add(BillingEvent(**row))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _mark(db: OrmSession, event_id: str, result: str, detail: str | None = None) -> None:
    """Дописывает итог в уже записанное событие."""
    row = db.get(BillingEvent, event_id)
    if row is None:  # pragma: no cover - строку только что вставили
        return
    row.result = result
    if detail:
        payload = dict(row.payload or {})
        payload["_result_detail"] = detail
        row.payload = payload
    db.commit()


# --- разбор события -----------------------------------------------------------


def _find_order(db: OrmSession, event: WebhookEvent) -> Order | None:
    """
    Заказ по событию.

    Сначала по своему идентификатору из метаданных — он надёжнее. Если
    провайдер его не вернул, ищем по паре «провайдер + идентификатор
    платежа»: она уникальна на уровне базы.
    """
    if event.order_id:
        order = db.get(Order, event.order_id)
        if order is not None:
            return order
    if event.payment_id:
        return db.scalar(
            select(Order).where(
                Order.provider == event.provider,
                Order.provider_payment_id == event.payment_id,
            )
        )
    return None


def _process(db: OrmSession, event: WebhookEvent) -> WebhookResult:
    order = _find_order(db, event)
    if order is None:
        log.error(
            "событие %s от %s не привязалось к заказу (payment_id=%s)",
            event.event_id,
            event.provider,
            event.payment_id,
        )
        return WebhookResult(UNKNOWN_ORDER, detail="заказ не найден")

    if event.is_refund:
        orders_service.refund(db, order, reason=f"возврат по событию {event.event_id}")
        return WebhookResult(REFUNDED, order_id=order.id)

    if not event.is_success:
        # Отмена и прочие промежуточные состояния: доступ не трогаем, но
        # неоплаченный заказ помечаем, чтобы он не висел сутки до крона.
        if order.status == OrderStatus.PENDING.value:
            order.status = OrderStatus.FAILED.value
            order.failure_reason = f"провайдер сообщил {event.kind}"
            db.commit()
        return WebhookResult(IGNORED, order_id=order.id, detail=event.kind)

    if order.status == OrderStatus.PAID.value:
        # Событие новое, а заказ уже оплачен: так бывает, когда провайдер
        # шлёт и `succeeded`, и `waiting_for_capture` с разными id событий.
        return WebhookResult(DUPLICATE, order_id=order.id, detail="заказ уже оплачен")

    # --- рубеж 3: сверка суммы ------------------------------------------------
    amount_note: str | None = None
    if event.amount_kopecks is None:
        # Суммы в уведомлении нет и получить её не удалось — так устроены
        # криптоплатежи. Уведомление при этом подписано секретом магазина,
        # то есть источник подтверждён; выдаём, но помечаем событие, чтобы
        # расхождение было видно в панели.
        amount_note = "сумма не подтверждена провайдером"
        log.warning("заказ %s: %s", order.id, amount_note)
    elif event.amount_kopecks != order.amount_kopecks or event.currency != order.currency:
        detail = (
            f"пришло {event.amount_kopecks / 100:.2f} {event.currency}, "
            f"ожидалось {order.amount_kopecks / 100:.2f} {order.currency}"
        )
        order.status = OrderStatus.FAILED.value
        order.failure_reason = f"сумма не совпала: {detail}"
        db.add(AuditLog(action="order.amount_mismatch", target=order.id, detail=detail))
        db.commit()
        log.error("заказ %s отклонён: %s", order.id, detail)
        return WebhookResult(AMOUNT_MISMATCH, order_id=order.id, detail=detail)

    if not order.provider_payment_id and event.payment_id:
        order.provider_payment_id = event.payment_id

    # --- рубеж 4: выдача одной транзакцией ------------------------------------
    fulfilment = orders_service.fulfil(db, order)
    log.info(
        "заказ %s оплачен: %s %s",
        order.id,
        fulfilment.user.public_id,
        "продление" if fulfilment.is_renewal else "новая учётка",
    )
    return WebhookResult(
        AMOUNT_UNVERIFIED if amount_note else OK, order_id=order.id, detail=amount_note
    )


# --- разбор застрявших --------------------------------------------------------


def retry_stuck(db: OrmSession, limit: int = 25) -> int:
    """
    Повторяет выдачу по событиям, обработка которых сорвалась.

    Признак — событие об успешной оплате с результатом `error`, а заказ при
    этом всё ещё не оплачен. Такое остаётся после падения процесса ровно
    между записью события и коммитом выдачи.
    """
    rows = list(
        db.scalars(
            select(BillingEvent)
            .where(BillingEvent.result == ERROR)
            .order_by(BillingEvent.received_at)
            .limit(limit)
        )
    )
    healed = 0
    for row in rows:
        order = db.get(Order, row.order_id) if row.order_id else None
        if order is None or order.status != OrderStatus.PENDING.value:
            row.result = IGNORED
            db.commit()
            continue
        try:
            orders_service.fulfil(db, order)
        except Exception:  # pragma: no cover - следующая попытка через цикл
            db.rollback()
            log.exception("повторная выдача по заказу %s не удалась", order.id)
            continue
        row.result = OK
        db.commit()
        healed += 1
        log.info("заказ %s выдан повторной попыткой", order.id)
    return healed
