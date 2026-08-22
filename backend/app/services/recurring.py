"""
Автопродление: подписки с автосписанием у Platega.

Устройство намеренно двухэтажное. Подписка здесь — это только обещание
провайдера списывать деньги по расписанию; сама она доступ не выдаёт.
Каждое подтверждённое списание превращается в обычный заказ и проходит
обычную выдачу (`orders.fulfil`) — с той же идемпотентностью, той же
сверкой суммы и теми же письмами, что и разовая оплата. Ломаться и
чиниться всё это должно в одном месте, а не в двух.

Статусами подписки управляют вебхуки провайдера и явная отмена. Панель
статусы не выдумывает: если Platega молчит, подписка выглядит так, как её
видел последний вебхук.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import (
    AuditLog,
    BillingEvent,
    DeliveryJob,
    Order,
    OrderStatus,
    Plan,
    RecurringStatus,
    RecurringSub,
    User,
    utcnow,
)
from ..payments import PaymentError, WebhookRejected, amount_to_kopecks
from ..payments import platega
from ..payments.base import WebhookEvent
from . import billing_webhook
from . import orders as orders_service
from .errors import PanelError

log = logging.getLogger("panel.recurring")

PROVIDER = "platega"

# Тариф → интервал Platega. Ключ — длительность тарифа в днях; кодов на 90 и
# 180 дней у Platega нет, такие тарифы продаются только разовыми платежами.
_INTERVALS: dict[int, tuple[str, str]] = {
    30: ("month", "3"),
    365: ("year", "4"),
}

# Человеческое слово для письма и кабинета.
INTERVAL_LABELS = {"month": "раз в месяц", "year": "раз в год"}


def plan_interval(plan: Plan) -> str | None:
    """month/year, если тариф ложится на расписание Platega, иначе None."""
    entry = _INTERVALS.get(plan.period_days)
    return entry[0] if entry else None


def eligible_plans(db: OrmSession) -> list[Plan]:
    """Тарифы, на которые можно подключить автосписание."""
    return [
        plan
        for plan in orders_service.public_plans(db)
        if plan_interval(plan) is not None
    ]


def get_live(db: OrmSession, user: User) -> RecurringSub | None:
    """
    Действующая (или оформляемая) подписка человека — последняя живая.

    Последняя, потому что историю не чистим: отменённые и сорвавшиеся
    остаются в таблице, по ним видно, что происходило с деньгами.
    """
    rows = db.scalars(
        select(RecurringSub)
        .where(RecurringSub.user_id == user.id)
        .order_by(RecurringSub.id.desc())
    )
    # Перебираем все строки, а не только последнюю: брошенную привязку можно
    # завершить по старой ссылке уже ПОСЛЕ того, как оформлена новая, — и
    # тогда живой окажется не самая свежая строка. Не найди мы её здесь,
    # подписка списывала бы деньги, будучи невидимой и неотключаемой.
    for row in rows:
        if row.is_live:
            return row
    return None


# --- оформление и отмена ------------------------------------------------------


def create(db: OrmSession, user: User, plan_code: str, origin: str = "site") -> RecurringSub:
    """
    Создаёт подписку у Platega и возвращает запись со ссылкой на привязку.

    Денег на этом шаге не движется: человек уходит по ссылке, подтверждает
    привязку счёта, и дальше всё делают вебхуки.
    """
    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None or not plan.is_active or plan.price_kopecks <= 0:
        raise PanelError("такого тарифа нет")
    interval = plan_interval(plan)
    if interval is None:
        raise PanelError("на этот тариф автосписание не подключается — оплатите разово")

    current = get_live(db, user)
    if current is not None and current.status != RecurringStatus.PENDING.value:
        raise PanelError("автосписание уже подключено — сначала отключите текущее")
    if current is not None:
        # Недооформленная с живой ссылкой на тот же тариф — возвращаем её же:
        # повторные нажатия не должны плодить подписки у провайдера, а
        # человек обязан попасть на ту привязку, которую уже начал.
        fresh = current.created_at > utcnow() - dt.timedelta(minutes=25)
        if (
            fresh
            and current.plan_code == plan.code
            and current.amount_kopecks == plan.price_kopecks
            and current.redirect_url
        ):
            return current
        # Другой тариф или протухшая ссылка: старую закрываем, заводим новую.
        # Закрываем и у провайдера: по брошенной ссылке из истории браузера
        # привязку можно завершить и через час — и жила бы подписка-сирота,
        # списывающая деньги мимо витрин. Отказ провайдера не рвёт оформление
        # новой: неактивированная привязка умрёт по своему таймеру.
        try:
            platega.api_request("POST", f"/subscription/{current.external_id}/cancel")
        except PaymentError as exc:
            log.warning("брошенную подписку %s не удалось отменить: %s", current.external_id, exc)
        current.status = RecurringStatus.FAILED.value
        current.last_charge_error = "привязка не завершена, оформлена новая"
        db.commit()

    body = {
        "paymentMethod": platega.SUBSCRIPTION_METHOD,
        "paymentDetails": {
            "amount": plan.price_kopecks / 100,
            "currency": plan.currency,
            "interval": _INTERVALS[plan.period_days][1],
        },
        # Это описание человек видит на форме привязки и в письмах Platega.
        "description": f"Prosto VPN — тариф «{plan.name}», автопродление",
        "payload": f"recurring:{user.id}:{plan.code}",
        "metadata": {"userId": str(user.id)},
    }
    try:
        data = platega.api_request("POST", "/transaction/process", body)
    except PaymentError as exc:
        log.error("создание подписки не удалось: %s", exc)
        detail = getattr(exc, "body", "") or ""
        if "paymentMethod" in detail and "Subscription" in detail:
            # Метод «Подписка» ещё не включён на мерчанте: это состояние на
            # стороне Platega, и человеку нужен честный ответ, а не «позже».
            raise PanelError(
                "автосписание ещё подключается платёжным сервисом — "
                "пока оплатите подписку разово"
            ) from exc
        raise PanelError("платёжный сервис сейчас недоступен, попробуйте позже") from exc
    external_id = data.get("transactionId")
    redirect = data.get("redirect") or data.get("url")
    if not external_id or not redirect:
        log.error("Platega не вернула transactionId/redirect подписки: %s", data)
        raise PanelError("не удалось создать подписку, попробуйте позже")

    sub = RecurringSub(
        provider=PROVIDER,
        external_id=str(external_id),
        user_id=user.id,
        plan_code=plan.code,
        amount_kopecks=plan.price_kopecks,
        currency=plan.currency,
        interval=interval,
        status=RecurringStatus.PENDING.value,
        redirect_url=str(redirect),
    )
    db.add(sub)
    try:
        db.commit()
    except IntegrityError:
        # Platega вернула id, который у нас уже есть, — повтор её ответа или
        # наш повторный запрос. Строку не плодим: освежаем существующую.
        db.rollback()
        sub = db.scalar(
            select(RecurringSub).where(
                RecurringSub.provider == PROVIDER,
                RecurringSub.external_id == str(external_id),
            )
        )
        if sub is None or sub.user_id != user.id:
            raise PanelError("подписка с таким идентификатором уже есть у другой учётки")
        sub.plan_code = plan.code
        sub.amount_kopecks = plan.price_kopecks
        sub.currency = plan.currency
        sub.interval = interval
        sub.status = RecurringStatus.PENDING.value
        sub.redirect_url = str(redirect)
        db.commit()
    db.add(
        AuditLog(
            action="recurring.create",
            target=user.public_id,
            detail=f"{plan.code}, {plan.price_kopecks / 100:.0f} {plan.currency} {INTERVAL_LABELS[interval]}, из {origin}",
        )
    )
    db.commit()
    db.refresh(sub)
    return sub


def cancel(db: OrmSession, sub: RecurringSub, reason: str = "по просьбе пользователя") -> None:
    """
    Останавливает списания. Ручка Platega идемпотентна, наша — тоже.

    Оплаченные дни не трогаем: отмена автосписания — не возврат денег, и
    доступ дожёвывает оплаченный период до конца.
    """
    if sub.status == RecurringStatus.CANCELLED.value:
        return

    # pending-подписку у Platega можно и не отменять — привязки ещё нет, —
    # но ручка идемпотентна и дешевле дёрнуть её всегда, чем разбирать
    # гонку «человек нажал „Отменить“ в момент активации».
    try:
        platega.api_request("POST", f"/subscription/{sub.external_id}/cancel")
    except PaymentError as exc:
        raise PanelError(f"не удалось отключить автосписание: {exc}") from exc

    sub.status = RecurringStatus.CANCELLED.value
    sub.cancelled_at = utcnow()
    db.add(AuditLog(action="recurring.cancel", target=sub.external_id, detail=reason))
    db.commit()
    _notify(db, sub, "recurring_off")


# --- вебхуки ------------------------------------------------------------------

OK = billing_webhook.OK
DUPLICATE = billing_webhook.DUPLICATE
UNKNOWN_SUB = "unknown_sub"
AMOUNT_MISMATCH = billing_webhook.AMOUNT_MISMATCH
AMOUNT_UNVERIFIED = billing_webhook.AMOUNT_UNVERIFIED
IGNORED = billing_webhook.IGNORED
ERROR = billing_webhook.ERROR


def handle_webhook(
    db: OrmSession,
    headers: dict[str, str],
    raw_body: bytes,
    client_ip: str | None,
) -> billing_webhook.WebhookResult:
    """
    Событие подписки: активация, смена статуса или списание.

    Тот же порядок рубежей, что и у разовых платежей: подлинность до
    разбора, идемпотентность вставкой, сверка суммы, и только потом выдача.
    """
    platega.authenticate(headers)
    payload = platega.parse_body(raw_body)

    status_name = str(payload.get("status") or "")
    sub_external = str(payload.get("subscriptionid") or payload.get("id") or "")
    if not sub_external:
        raise WebhookRejected("в событии подписки нет идентификатора")

    if status_name.startswith("SUBSCRIPTION_"):
        kind = "sub.status"
        event_id = f"platega-sub:{sub_external}:{status_name}"
        payment_id = None
    else:
        # Списание: id — идентификатор транзакции-списания, свой на каждое.
        kind = "sub.charge"
        payment_id = str(payload.get("id") or "")
        if not payment_id:
            raise WebhookRejected("в списании нет идентификатора транзакции")
        event_id = f"platega-charge:{payment_id}:{status_name}"

    try:
        kopecks = amount_to_kopecks(payload["amount"]) if "amount" in payload else None
    except (ValueError, TypeError, ArithmeticError):
        kopecks = None

    event = WebhookEvent(
        event_id=event_id,
        kind=kind,
        provider=PROVIDER,
        order_id=None,
        payment_id=payment_id,
        amount_kopecks=kopecks,
        currency=str(payload.get("currency") or "RUB"),
        raw=payload,
    )

    if not billing_webhook.claim_event(db, event):
        log.info("повтор события подписки %s — пропущено", event_id)
        return billing_webhook.WebhookResult(DUPLICATE)

    try:
        result = _process(db, event, status_name, sub_external)
    except Exception as exc:  # ошибки обработки не превращаются в 500
        db.rollback()
        log.exception("обработка события подписки %s провалилась", event_id)
        billing_webhook.mark_event(db, event_id, ERROR, str(exc)[:500])
        return billing_webhook.WebhookResult(ERROR, detail=str(exc))

    billing_webhook.mark_event(db, event_id, result.result, result.detail)
    return result


def _process(
    db: OrmSession, event: WebhookEvent, status_name: str, sub_external: str
) -> billing_webhook.WebhookResult:
    sub = db.scalar(
        select(RecurringSub).where(
            RecurringSub.provider == PROVIDER, RecurringSub.external_id == sub_external
        )
    )
    if sub is None:
        log.error("событие %s не привязалось к подписке %s", event.event_id, sub_external)
        return billing_webhook.WebhookResult(UNKNOWN_SUB, detail="подписка не найдена")

    next_charge = _parse_moment(event.raw.get("nextchargeat"))

    if status_name == "SUBSCRIPTION_ACTIVATED":
        fresh = sub.status != RecurringStatus.ACTIVE.value
        sub.status = RecurringStatus.ACTIVE.value
        sub.activated_at = sub.activated_at or utcnow()
        sub.last_charge_error = None
        if next_charge:
            sub.next_charge_at = next_charge
        db.commit()
        if fresh:
            _notify(db, sub, "recurring_on")
        log.info("подписка %s активирована", sub.external_id)
        return billing_webhook.WebhookResult(OK)

    if status_name == "SUBSCRIPTION_CANCELLED":
        already = sub.status == RecurringStatus.CANCELLED.value
        sub.status = RecurringStatus.CANCELLED.value
        sub.cancelled_at = sub.cancelled_at or utcnow()
        db.commit()
        if not already:
            # Отмену с нашей стороны человек уже увидел — письмо ушло из
            # cancel(). Сюда попадает отмена со стороны Platega или банка.
            _notify(db, sub, "recurring_off")
        return billing_webhook.WebhookResult(OK)

    if status_name == "SUBSCRIPTION_FAILED":
        sub.status = RecurringStatus.FAILED.value
        sub.last_charge_error = "привязка счёта не удалась"
        db.commit()
        # Без письма: человек видел отказ на форме привязки, писать ему о
        # том же ещё раз — только пугать.
        return billing_webhook.WebhookResult(OK)

    if status_name == "SUBSCRIPTION_PAST_DUE":
        sub.status = RecurringStatus.PAST_DUE.value
        db.commit()
        # Письмо шлёт отказ конкретного списания (CANCELED ниже) — у него
        # есть сумма и дата, у этого статуса нет ничего.
        return billing_webhook.WebhookResult(OK)

    if status_name == "CONFIRMED":
        return _confirm_charge(db, sub, event, next_charge)

    if status_name == "CANCELED":
        sub.status = RecurringStatus.PAST_DUE.value
        sub.last_charge_error = "списание не прошло"
        sub.next_charge_at = next_charge
        db.commit()
        _notify(db, sub, "recurring_failed")
        log.warning("подписка %s: списание %s не прошло", sub.external_id, event.payment_id)
        return billing_webhook.WebhookResult(OK, detail="списание не прошло")

    log.error("подписка %s: неизвестный статус %r", sub.external_id, status_name)
    return billing_webhook.WebhookResult(IGNORED, detail=f"статус {status_name!r}")


def _confirm_charge(
    db: OrmSession,
    sub: RecurringSub,
    event: WebhookEvent,
    next_charge: dt.datetime | None,
) -> billing_webhook.WebhookResult:
    """
    Подтверждённое списание → обычный заказ → обычная выдача.

    Сумма сверяется с той, на которую человек подписывался, — она лежит у
    нас, а не в теле уведомления. Расхождение — это смена цены без ведома
    человека или подделка; в обоих случаях доступ не выдаётся, а событие
    остаётся администратору.
    """
    user = db.get(User, sub.user_id)
    if user is None:
        return billing_webhook.WebhookResult(UNKNOWN_SUB, detail="пользователь удалён")

    if event.amount_kopecks is None:
        note = "в списании нет суммы"
        db.add(AuditLog(action="recurring.amount_unverified", target=sub.external_id, detail=note))
        db.commit()
        return billing_webhook.WebhookResult(AMOUNT_UNVERIFIED, detail=note)

    kopecks = event.amount_kopecks
    # Перепроверка через API — как у разовых платежей. Списание — это
    # транзакция, и она видна в GET /transaction. Если API молчит,
    # довольствуемся совпавшим секретом и сверкой с нашей суммой: держать
    # продление всех подписчиков на доступности одного GET нельзя.
    confirmed = _fetch_transaction(event.payment_id)
    if confirmed is not None:
        api_status = str(confirmed.get("status") or "")
        if api_status != "CONFIRMED":
            note = f"уведомление говорит «списано», API — {api_status!r}"
            db.add(AuditLog(action="recurring.status_mismatch", target=sub.external_id, detail=note))
            db.commit()
            return billing_webhook.WebhookResult(AMOUNT_UNVERIFIED, detail=note)
        details = confirmed.get("paymentDetails") or {}
        if isinstance(details, dict) and "amount" in details:
            try:
                kopecks = amount_to_kopecks(details["amount"])
            except (ValueError, TypeError, ArithmeticError):
                pass

    if kopecks != sub.amount_kopecks:
        detail = (
            f"пришло {kopecks / 100:.2f}, подписка на {sub.amount_kopecks / 100:.2f} {sub.currency}"
        )
        db.add(AuditLog(action="recurring.amount_mismatch", target=sub.external_id, detail=detail))
        db.commit()
        log.error("подписка %s: %s", sub.external_id, detail)
        return billing_webhook.WebhookResult(AMOUNT_MISMATCH, detail=detail)

    order = Order(
        plan_code=sub.plan_code,
        email=user.email_plain or "",
        telegram_id=user.telegram_id,
        amount_kopecks=sub.amount_kopecks,
        currency=sub.currency,
        status=OrderStatus.PENDING.value,
        provider=PROVIDER,
        provider_payment_id=event.payment_id,
        origin="recurring",
        user_id=user.id,
        is_renewal=True,
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        # (provider, provider_payment_id) уникальны: это же списание уже
        # приходило под другим идентификатором события.
        db.rollback()
        return billing_webhook.WebhookResult(DUPLICATE, detail="списание уже учтено")

    fulfilment = orders_service.fulfil(db, order)

    sub.status = RecurringStatus.ACTIVE.value
    sub.last_charge_at = utcnow()
    sub.last_charge_error = None
    sub.next_charge_at = next_charge
    db.commit()

    log.info(
        "подписка %s: списание %s выдано, доступ до %s",
        sub.external_id,
        event.payment_id,
        fulfilment.expires_at.date(),
    )
    return billing_webhook.WebhookResult(OK, order_id=order.id)


def retry_stuck(db: OrmSession, limit: int = 25) -> int:
    """
    Повторяет события подписок, обработка которых сорвалась.

    Провайдер повтора не пришлёт: событие уже застолблено, и вторая доставка
    уходит дубликатом. Значит, упавшее списание вылечит только обходчик.
    Повторять безопасно: выдача по списанию идемпотентна уникальностью
    (provider, provider_payment_id) на заказах, а смены статусов подписки
    идемпотентны сами по себе. Не повторяются расхождения суммы — по ним
    решает администратор.
    """
    deadline = utcnow() - dt.timedelta(minutes=billing_webhook.RETRY_AFTER_MINUTES)
    stale = utcnow() - dt.timedelta(minutes=billing_webhook.RETRYING_STALE_MINUTES)
    rows = list(
        db.scalars(
            select(BillingEvent)
            .where(
                BillingEvent.provider == PROVIDER,
                BillingEvent.kind.like("sub.%"),
                or_(
                    and_(BillingEvent.result.is_(None), BillingEvent.received_at < deadline),
                    and_(
                        BillingEvent.result == billing_webhook.ERROR,
                        BillingEvent.received_at < deadline,
                    ),
                    and_(
                        BillingEvent.result == billing_webhook.RETRYING,
                        BillingEvent.received_at < stale,
                    ),
                ),
            )
            .order_by(BillingEvent.received_at)
            .limit(limit)
        )
    )

    healed = 0
    for row in rows:
        event = _restore_sub_event(row)
        if event is None:
            log.error("событие подписки %s не восстановить", row.event_id)
            billing_webhook.mark_event(db, row.event_id, ERROR, "не восстановить")
            continue
        if not billing_webhook.claim_for_retry(db, row):
            continue

        status_name = str(event.raw.get("status") or "")
        sub_external = str(event.raw.get("subscriptionid") or event.raw.get("id") or "")
        try:
            result = _process(db, event, status_name, sub_external)
        except Exception as exc:  # pragma: no cover - следующая попытка через цикл
            db.rollback()
            log.exception("повтор события подписки %s не удался", row.event_id)
            billing_webhook.mark_event(db, row.event_id, ERROR, str(exc)[:500])
            continue
        billing_webhook.mark_event(db, row.event_id, result.result, result.detail)
        if result.result == OK:
            healed += 1
            log.info("событие подписки %s доработано повторной попыткой", row.event_id)
    return healed


def _restore_sub_event(row: BillingEvent) -> WebhookEvent | None:
    """Событие из журнала — чтобы повторить его тем же путём, что и живое."""
    payload = dict(row.payload or {})
    checked = payload.pop(billing_webhook.CHECKED_KEY, None)
    if not isinstance(checked, dict) or not str(payload.get("status") or ""):
        return None
    return WebhookEvent(
        event_id=row.event_id,
        kind=row.kind or "sub.charge",
        provider=PROVIDER,
        order_id=None,
        payment_id=checked.get("payment_id"),
        amount_kopecks=checked.get("amount_kopecks"),
        currency=checked.get("currency") or "RUB",
        raw=payload,
    )


def _fetch_transaction(transaction_id: str | None) -> dict | None:
    if not transaction_id:
        return None
    try:
        return platega.api_request("GET", f"/transaction/{transaction_id}")
    except PaymentError as exc:
        log.warning("не удалось перепроверить списание %s: %s", transaction_id, exc)
        return None


def _parse_moment(value: object) -> dt.datetime | None:
    """ISO-время Platega («2026-08-09T09:10:00Z») → наивный UTC, как во всей базе."""
    if not value or not isinstance(value, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return moment


# --- письма -------------------------------------------------------------------


def _notify(db: OrmSession, sub: RecurringSub, template: str) -> None:
    """
    Задания на письмо и сообщение — тем же транзакционным outbox-ом, что и
    выдача. Пользователь без почты получает только Telegram, без Telegram —
    только письмо; без того и другого молчим и не падаем.
    """
    user = db.get(User, sub.user_id)
    if user is None:
        return
    email = user.email_plain
    if email:
        db.add(DeliveryJob(channel="email", template=template, target=email, user_id=user.id))
    if user.telegram_id:
        db.add(
            DeliveryJob(
                channel="telegram", template=template, target=str(user.telegram_id), user_id=user.id
            )
        )
    db.commit()
