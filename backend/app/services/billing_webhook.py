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
   причиной, видимой администратору. Если суммы нет вовсе и подтвердить её
   не удалось, доступ тоже не выдаётся: подпись говорит лишь «источник
   настоящий», а сверять не с чем — заказ ждёт подтверждения из панели.

4. **200 почти всегда.** Как только событие записано, провайдеру отвечают
   успехом. Ошибка нашей обработки — наша проблема, и решается повторной
   попыткой из панели или обходчиком, а не 500-м ответом: на 500 провайдер
   начнёт долбить эндпоинт и может создать дубли на соседних узлах.
"""

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

# Что записывается в billing_events.result и попадает в админку.
OK = "ok"
DUPLICATE = "duplicate"
UNKNOWN_ORDER = "unknown_order"
AMOUNT_MISMATCH = "amount_mismatch"
AMOUNT_UNVERIFIED = "amount_unverified"
IGNORED = "ignored"
REFUNDED = "refunded"
ERROR = "error"
# Рубежи 1-3 пройдены, выдача ещё нет: отдельным коммитом, чтобы этот факт
# пережил откат неудавшейся выдачи. Только такие события и повторяются.
READY = "ready_to_fulfil"
ERROR_AFTER_CHECKS = "error_after_checks"
RETRYING = "retrying"

# Нормализованные поля события внутри payload. Отдельных колонок под них в
# billing_events нет, а без них повторить обработку нечем: заголовки и сырое
# тело не сохраняются, да и сумму часть провайдеров берёт не из тела, а
# отдельным запросом к своему API.
CHECKED_KEY = "_event"

# Сколько ждать, прежде чем считать событие без результата застрявшим.
# Заведомо больше самой долгой обработки: событие «в работе прямо сейчас»
# подхватывать нельзя.
RETRY_AFTER_MINUTES = 10
# Повтор, застрявший в RETRYING, — процесс убили посреди работы. Порог
# больше обычного: живому повтору нужно время дообработаться.
RETRYING_STALE_MINUTES = 30


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
        _mark_failure(db, event.event_id, exc)
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
        # order_id — внешний ключ на orders. Заказа с таким идентификатором
        # может не быть вовсе (чужая база, удалённый заказ, произвольное
        # значение в уведомлении), и тогда вставка упала бы IntegrityError
        # раньше, чем событие попадёт в журнал, а провайдер получил бы 500.
        # Само значение не теряется: оно лежит в payload, и заказ ищется по
        # событию, а не по этой колонке.
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

    # Прочие СУБД: та же семантика через нарушение первичного ключа.
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
    """
    Атомно переводит событие в RETRYING. False — забрал другой воркер.

    UPDATE со сверкой прежнего результата, а не присваивание в объекте:
    присваивание после общего SELECT выигрывают оба воркера сразу, и оба
    идут обрабатывать одно событие.
    """
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


# Те же рубежи нужны событиям подписок (services/recurring.py): застолбить
# вставкой и дописать итог. Публичные имена, чтобы не звать приватное чужое.
def claim_event(db: OrmSession, event: WebhookEvent) -> bool:
    return _claim(db, event)


def mark_event(db: OrmSession, event_id: str, result: str, detail: str | None = None) -> None:
    _mark(db, event_id, result, detail)


def claim_for_retry(db: OrmSession, row: BillingEvent) -> bool:
    return _claim_for_retry(db, row)


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


def _mark_failure(db: OrmSession, event_id: str, exc: Exception) -> None:
    """
    Итог сорвавшейся обработки.

    Различие принципиальное: событие, дошедшее до READY, все проверки уже
    прошло, и повторить выдачу по нему безопасно. Всё остальное упало до
    сверки суммы или вовсе не было успешным — такое повторять вслепую
    нельзя, им занимается администратор.
    """
    row = db.get(BillingEvent, event_id)
    passed = row is not None and row.result == READY
    _mark(db, event_id, ERROR_AFTER_CHECKS if passed else ERROR, str(exc)[:500])


def _restore(row: BillingEvent) -> WebhookEvent | None:
    """Событие из журнала — чтобы повторить его тем же путём, что и живое."""
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


# --- разбор события -----------------------------------------------------------


def _find_order(db: OrmSession, event: WebhookEvent) -> Order | None:
    """
    Заказ по событию.

    Сначала по своему идентификатору из метаданных — он надёжнее. Если
    провайдер его не вернул, ищем по паре «провайдер + идентификатор
    платежа»: она уникальна на уровне базы.

    В обоих случаях провайдер заказа обязан совпасть с провайдером события.
    Иначе уведомление от одного платёжного сервиса закрывало бы заказ,
    заведённый в другом, — а идентификатор заказа публичен и приходит в
    ответе на его создание.
    """
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

    if order.status == OrderStatus.REFUNDED.value:
        # По заказу уже был возврат. Выдавать по нему нельзя, каким бы путём
        # ни пришло подтверждение — опоздавшим вебхуком или обходчиком
        # застрявших: деньги вернулись клиенту, и «оплачено» это не отменяет.
        # Ручная выдача в панели отвергает такой заказ по той же причине.
        return WebhookResult(IGNORED, order_id=order.id, detail="по заказу был возврат")

    # --- рубеж 3: сверка суммы ------------------------------------------------
    if event.amount_kopecks is None:
        # Суммы нет и получить её не удалось. Выдавать по такому событию
        # нельзя: подпись подтверждает только источник, а сколько и за что
        # заплачено — неизвестно, и сверять не с чем. Заказ остаётся
        # неоплаченным, событие видно в панели, выдача — кнопкой вручную.
        note = "сумма не подтверждена провайдером"
        db.add(AuditLog(action="order.amount_unverified", target=order.id, detail=note))
        db.commit()
        log.error("заказ %s не выдан: %s", order.id, note)
        return WebhookResult(AMOUNT_UNVERIFIED, order_id=order.id, detail=note)

    if event.amount_kopecks != order.amount_kopecks or event.currency != order.currency:
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

    # Отметка «рубежи пройдены» — отдельным коммитом и до выдачи. Если
    # выдача сорвётся, её откат эту отметку не унесёт, и обходчик поймёт,
    # что событие можно повторять: проверки по нему уже сделаны.
    _mark(db, event.event_id, READY)

    # --- рубеж 4: выдача одной транзакцией ------------------------------------
    fulfilment = orders_service.fulfil(db, order)
    log.info(
        "заказ %s оплачен: %s %s",
        order.id,
        fulfilment.user.public_id,
        "продление" if fulfilment.is_renewal else "новая учётка",
    )
    return WebhookResult(OK, order_id=order.id)


# --- разбор застрявших --------------------------------------------------------


def retry_stuck(db: OrmSession, limit: int = 25) -> int:
    """
    Повторяет обработку событий, которая сорвалась.

    Два признака. Первый — рубежи пройдены, а выдача не закоммитилась
    (`ready_to_fulfil`, `error_after_checks`). Второй — событие записано, а
    результата так и нет: процесс убили между вставкой события и концом
    обработки. Повторной доставки в этом случае не будет — провайдер уже
    получил 200 на первую, — и вылечить такое может только обходчик.

    Голого `error` здесь нет намеренно: там обработка упала до сверки суммы
    или событие вовсе не было успешным, и повтор вслепую выдал бы доступ по
    отменённому платежу. Такое остаётся администратору.

    Повторяем не выдачей напрямую, а тем же `_process`: он один знает про
    возвраты, отмены и сверку суммы, а `fulfil` выдал бы доступ по любому
    событию, какое ему принесли.
    """
    # Порог возраста для всех веток, включая READY: отметка «рубежи пройдены»
    # ставится за мгновение до выдачи, и свежая строка почти наверняка
    # обрабатывается прямо сейчас — обходчику там делать нечего.
    deadline = utcnow() - dt.timedelta(minutes=RETRY_AFTER_MINUTES)
    # Застрявший RETRYING — процесс убили посреди повтора. Порог больше:
    # живому повтору надо успеть дообработаться.
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
                # События подписок (sub.status, sub.charge) живут по своим
                # правилам в services/recurring.py: заказный _process по ним
                # только зря пометил бы «не восстановить».
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
            # Запись старого образца, без нормализованных полей. Разбирать
            # сырое тело заново — значит доверять неподписанному: пусть
            # лучше событие ждёт человека.
            log.error("событие %s не восстановить, нужна ручная выдача", row.event_id)
            row.result = ERROR
            db.commit()
            continue

        # Захват сравнением-с-обменом: строку из выборки забирает ровно один
        # обходчик. Два воркера, взявшие один список, не должны выдать по
        # событию дважды — проигравший увидит rowcount 0 и пройдёт мимо.
        if not _claim_for_retry(db, row):
            continue
        try:
            result = _process(db, event)
        except Exception as exc:  # pragma: no cover - следующая попытка через цикл
            db.rollback()
            log.exception("повторная обработка события %s не удалась", row.event_id)
            _mark_failure(db, row.event_id, exc)
            continue
        _mark(db, row.event_id, result.result, result.detail)
        if result.result in (OK, REFUNDED):
            healed += 1
            log.info("событие %s доработано повторной попыткой", row.event_id)
    return healed
