from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy import and_, or_, select, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .. import payments
from ..models import AuditLog, BillingEvent, Order, OrderStatus, utcnow
from ..payments.base import WebhookEvent
from . import orders as orders_service

log = logging.getLogger("panel.webhook")

OK = "ok"
DUPLICATE = "duplicate"
UNKNOWN_ORDER = "unknown_order"
AMOUNT_MISMATCH = "amount_mismatch"
AMOUNT_UNVERIFIED = "amount_unverified"
IGNORED = "ignored"
REFUNDED = "refunded"
ERROR = "error"
READY = "ready_to_fulfil"
ERROR_AFTER_CHECKS = "error_after_checks"
RETRYING = "retrying"

CHECKED_KEY = "_event"

RETRY_AFTER_MINUTES = 10
RETRYING_STALE_MINUTES = 30


@dataclass(slots=True)
class WebhookResult:

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
    provider = payments.get(provider_name)

    event = provider.verify_webhook(headers, raw_body, client_ip)

    if not _claim(db, event):
        log.info("повтор события %s от %s — пропущено", event.event_id, provider_name)
        return WebhookResult(DUPLICATE, order_id=event.order_id)

    try:
        result = _process(db, event)
    except Exception as exc:
        db.rollback()
        log.exception("обработка события %s провалилась", event.event_id)
        _mark_failure(db, event.event_id, exc)
        return WebhookResult(ERROR, order_id=event.order_id, detail=str(exc))

    _mark(db, event.event_id, result.result, result.detail)
    return result


def apply_event(db: OrmSession, event: WebhookEvent) -> WebhookResult:
    """Провести событие, собранное нами самими (вотчер TON), минуя verify."""
    if not _claim(db, event):
        return WebhookResult(DUPLICATE, order_id=event.order_id)

    try:
        result = _process(db, event)
    except Exception as exc:
        db.rollback()
        log.exception("обработка события %s провалилась", event.event_id)
        _mark_failure(db, event.event_id, exc)
        return WebhookResult(ERROR, order_id=event.order_id, detail=str(exc))

    _mark(db, event.event_id, result.result, result.detail)
    return result


def _claim(db: OrmSession, event: WebhookEvent) -> bool:
    payload = dict(event.raw or {})
    payload[CHECKED_KEY] = {
        "order_id": event.order_id,
        "payment_id": event.payment_id,
        "amount_kopecks": event.amount_kopecks,
        "currency": event.currency,
    }

    row = {
        "event_id": event.event_id,
        "provider": event.provider,
        "kind": event.kind,
        "order_id": event.order_id if _order_exists(db, event.order_id) else None,
        "payload": payload,
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

    try:
        db.add(BillingEvent(**row))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _order_exists(db: OrmSession, order_id: str | None) -> bool:
    return bool(order_id) and db.get(Order, order_id) is not None


def _claim_for_retry(db: OrmSession, row: BillingEvent) -> bool:
    condition = (
        BillingEvent.result.is_(None) if row.result is None else BillingEvent.result == row.result
    )
    claimed = db.execute(
        sa_update(BillingEvent)
        .where(BillingEvent.event_id == row.event_id, condition)
        .values(result=RETRYING)
    ).rowcount
    db.commit()
    return bool(claimed)


def claim_event(db: OrmSession, event: WebhookEvent) -> bool:
    return _claim(db, event)


def mark_event(db: OrmSession, event_id: str, result: str, detail: str | None = None) -> None:
    _mark(db, event_id, result, detail)


def claim_for_retry(db: OrmSession, row: BillingEvent) -> bool:
    return _claim_for_retry(db, row)


def _mark(db: OrmSession, event_id: str, result: str, detail: str | None = None) -> None:
    row = db.get(BillingEvent, event_id)
    if row is None:
        return
    row.result = result
    if detail:
        payload = dict(row.payload or {})
        payload["_result_detail"] = detail
        row.payload = payload
    db.commit()


def _mark_failure(db: OrmSession, event_id: str, exc: Exception) -> None:
    row = db.get(BillingEvent, event_id)
    passed = row is not None and row.result == READY
    _mark(db, event_id, ERROR_AFTER_CHECKS if passed else ERROR, str(exc)[:500])


def _restore(row: BillingEvent) -> WebhookEvent | None:
    payload = dict(row.payload or {})
    checked = payload.pop(CHECKED_KEY, None)
    if not isinstance(checked, dict) or not row.kind:
        return None
    return WebhookEvent(
        event_id=row.event_id,
        kind=row.kind,
        provider=row.provider,
        order_id=checked.get("order_id") or row.order_id,
        payment_id=checked.get("payment_id"),
        amount_kopecks=checked.get("amount_kopecks"),
        currency=checked.get("currency") or "RUB",
        raw=payload,
    )


def _find_order(db: OrmSession, event: WebhookEvent) -> Order | None:
    if event.order_id:
        order = db.get(Order, event.order_id)
        if order is not None and order.provider != event.provider:
            log.error(
                "событие %s от %s указывает на заказ %s провайдера %s — отвергнуто",
                event.event_id,
                event.provider,
                order.id,
                order.provider,
            )
        elif order is not None:
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
        if order.status == OrderStatus.PENDING.value:
            order.status = OrderStatus.FAILED.value
            order.failure_reason = f"провайдер сообщил {event.kind}"
            db.commit()
        return WebhookResult(IGNORED, order_id=order.id, detail=event.kind)

    if order.status == OrderStatus.PAID.value:
        return WebhookResult(DUPLICATE, order_id=order.id, detail="заказ уже оплачен")

    if order.status == OrderStatus.REFUNDED.value:
        return WebhookResult(IGNORED, order_id=order.id, detail="по заказу был возврат")

    if event.amount_kopecks is None:
        note = "сумма не подтверждена провайдером"
        db.add(AuditLog(action="order.amount_unverified", target=order.id, detail=note))
        db.commit()
        log.error("заказ %s не выдан: %s", order.id, note)
        return WebhookResult(AMOUNT_UNVERIFIED, order_id=order.id, detail=note)

    detail = (
        f"пришло {event.amount_kopecks / 100:.2f} {event.currency}, "
        f"ожидалось {order.amount_kopecks / 100:.2f} {order.currency}"
    )

    if event.currency != order.currency:
        order.status = OrderStatus.FAILED.value
        order.failure_reason = f"валюта не совпала: {detail}"
        db.add(AuditLog(action="order.currency_mismatch", target=order.id, detail=detail))
        db.commit()
        log.error("заказ %s отклонён, валюта: %s", order.id, detail)
        return WebhookResult(AMOUNT_MISMATCH, order_id=order.id, detail=detail)

    if event.amount_kopecks < order.amount_kopecks:
        order.status = OrderStatus.FAILED.value
        order.failure_reason = f"заплачено меньше цены: {detail}"
        db.add(AuditLog(action="order.amount_mismatch", target=order.id, detail=detail))
        db.commit()
        log.error("заказ %s отклонён, недоплата: %s", order.id, detail)
        return WebhookResult(AMOUNT_MISMATCH, order_id=order.id, detail=detail)

    if event.amount_kopecks != order.amount_kopecks:
        db.add(AuditLog(action="order.amount_over", target=order.id, detail=detail))
        log.warning("заказ %s: заплачено больше цены, выдаём — %s", order.id, detail)

    if not order.provider_payment_id and event.payment_id:
        order.provider_payment_id = event.payment_id

    _mark(db, event.event_id, READY)

    fulfilment = orders_service.fulfil(db, order)
    log.info(
        "заказ %s оплачен: %s %s",
        order.id,
        fulfilment.user.public_id,
        "продление" if fulfilment.is_renewal else "новая учётка",
    )
    return WebhookResult(OK, order_id=order.id)


def retry_stuck(db: OrmSession, limit: int = 25) -> int:
    deadline = utcnow() - dt.timedelta(minutes=RETRY_AFTER_MINUTES)
    retrying_deadline = utcnow() - dt.timedelta(minutes=RETRYING_STALE_MINUTES)
    rows = list(
        db.scalars(
            select(BillingEvent)
            .where(
                or_(
                    and_(
                        BillingEvent.result.in_((READY, ERROR_AFTER_CHECKS)),
                        BillingEvent.received_at < deadline,
                    ),
                    and_(
                        BillingEvent.result.is_(None),
                        BillingEvent.received_at < deadline,
                    ),
                    and_(
                        BillingEvent.result == RETRYING,
                        BillingEvent.received_at < retrying_deadline,
                    ),
                ),
                or_(BillingEvent.kind.is_(None), BillingEvent.kind.notlike("sub.%")),
            )
            .order_by(BillingEvent.received_at)
            .limit(limit)
        )
    )
    healed = 0
    for row in rows:
        event = _restore(row)
        if event is None:
            log.error("событие %s не восстановить, нужна ручная выдача", row.event_id)
            row.result = ERROR
            db.commit()
            continue

        if not _claim_for_retry(db, row):
            continue
        try:
            result = _process(db, event)
        except Exception as exc:
            db.rollback()
            log.exception("повторная обработка события %s не удалась", row.event_id)
            _mark_failure(db, row.event_id, exc)
            continue
        _mark(db, row.event_id, result.result, result.detail)
        if result.result in (OK, REFUNDED):
            healed += 1
            log.info("событие %s доработано повторной попыткой", row.event_id)
    return healed
