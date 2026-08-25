from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    BillingEvent,
    Order,
    OrderStatus,
    Payment,
    Plan,
    Provisioning,
    Server,
    Subscription,
    User,
    utcnow,
)
from app.payments import platega
from app.payments.base import WebhookEvent
from app.services import billing_webhook
from app.services import recurring as recurring_service

MERCHANT = "11111111-2222-3333-4444-555555555555"
SECRET = "test-platega-secret"
GOOD_HEADERS = {"X-MerchantId": MERCHANT, "X-Secret": SECRET}
WEBHOOK = "/api/v1/billing/webhook/platega"


@pytest.fixture(scope="module")
def client():
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(Server).limit(1)) is None:
            db.add(
                Server(
                    name="test-nl",
                    country="Нидерланды",
                    country_code="NL",
                    host="10.20.30.1",
                    provisioning=Provisioning.SHARED,
                    shared_config="[Interface]\nAddress = 10.0.0.2/32\n",
                )
            )
            db.commit()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fake_api(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []
    routes: dict[tuple[str, str], object] = {}

    def request(method: str, path: str, body: dict | None = None) -> dict:
        calls.append((method, path, body))
        key = (method, path)
        if key not in routes:
            raise platega.PaymentError(f"нет маршрута {method} {path}")
        answer = routes[key]
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)

    monkeypatch.setattr(platega, "api_request", request)
    return {"calls": calls, "routes": routes}


def _post_webhook(client, payload: dict):
    return client.post(
        WEBHOOK,
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **GOOD_HEADERS},
    )


def _pay_order(client, fake_api, order_id: str, tx: str, amount: float) -> None:
    fake_api["routes"][("GET", f"/transaction/{tx}")] = {
        "id": tx,
        "status": "CONFIRMED",
        "paymentDetails": {"amount": amount, "currency": "RUB"},
    }
    r = _post_webhook(
        client,
        {
            "id": tx,
            "amount": amount,
            "currency": "RUB",
            "status": "CONFIRMED",
            "paymentMethod": 2,
            "payload": order_id,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "ok", r.text


def _order_for(client, fake_api, email: str, tx: str) -> str:
    from app.services import create_order

    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": tx,
        "redirect": f"https://pay.platega.io/?id={tx}",
        "expiresIn": "00:30:00",
    }
    with SessionLocal() as db:
        order = create_order(db, plan_code="basic", email=email, provider_name="platega")
        return order.id


def test_refund_of_one_renewal_keeps_other_paid_days(client, fake_api):
    first_id = _order_for(client, fake_api, "audit-refund@example.com", "tx-ref-1")
    _pay_order(client, fake_api, first_id, "tx-ref-1", 199)

    with SessionLocal() as db:
        first = db.get(Order, first_id)
        user_id = first.user_id
        sub_id = first.subscription_id

    from app.services import create_order_for_user

    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": "tx-ref-2",
        "redirect": "https://pay.platega.io/?id=tx-ref-2",
        "expiresIn": "00:30:00",
    }
    with SessionLocal() as db:
        user = db.get(User, user_id)
        second = create_order_for_user(db, user, "basic", provider_name="platega")
        second_id = second.id
    _pay_order(client, fake_api, second_id, "tx-ref-2", 199)

    with SessionLocal() as db:
        second = db.get(Order, second_id)
        assert second.subscription_id == sub_id, "продление того же тарифа делит строку подписки"
        expires_after_two = db.get(Subscription, sub_id).expires_at

    r = _post_webhook(
        client,
        {
            "id": "tx-ref-2",
            "amount": 199,
            "currency": "RUB",
            "status": "CHARGEBACKED",
            "paymentMethod": 2,
            "payload": second_id,
        },
    )
    assert r.json()["result"] == "refunded"

    with SessionLocal() as db:
        sub = db.get(Subscription, sub_id)
        user = db.get(User, user_id)
        plan = db.scalar(select(Plan).where(Plan.code == "basic"))
        assert not sub.is_cancelled, "первая оплата не оспорена — подписка живёт"
        assert (expires_after_two - sub.expires_at).days == plan.period_days
        assert not user.is_blocked, "возврат одного продления не должен банить"
        assert user.has_access(utcnow()), "оплаченные дни первого заказа остаются"
        amounts = sorted(
            float(p.amount) for p in db.scalars(select(Payment).where(Payment.user_id == user_id))
        )
        assert amounts == [-199.0, 199.0, 199.0]


def test_confirmed_after_refund_does_not_grant(client, fake_api):
    order_id = _order_for(client, fake_api, "audit-late@example.com", "tx-late-1")

    r = _post_webhook(
        client,
        {
            "id": "tx-late-1",
            "amount": 199,
            "currency": "RUB",
            "status": "CHARGEBACKED",
            "paymentMethod": 2,
            "payload": order_id,
        },
    )
    assert r.json()["result"] == "refunded"

    _pay = fake_api["routes"][("GET", "/transaction/tx-late-1")] = {
        "id": "tx-late-1",
        "status": "CONFIRMED",
        "paymentDetails": {"amount": 199, "currency": "RUB"},
    }
    r = _post_webhook(
        client,
        {
            "id": "tx-late-1",
            "amount": 199,
            "currency": "RUB",
            "status": "CONFIRMED",
            "paymentMethod": 2,
            "payload": order_id,
        },
    )
    assert r.json()["result"] == "ignored"

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        assert order.status == OrderStatus.REFUNDED.value
        assert order.user_id is None, "доступ по возвращённому заказу не выдаётся"


def test_lost_subscription_charge_is_healed_by_retry(client, fake_api):
    order_id = _order_for(client, fake_api, "audit-retry@example.com", "tx-retry-1")
    _pay_order(client, fake_api, order_id, "tx-retry-1", 199)
    with SessionLocal() as db:
        user_id = db.get(Order, order_id).user_id
        expires_before = db.get(User, user_id).active_subscription().expires_at

    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": "sub-retry-1",
        "redirect": "https://pay.platega.io/subscription/sub-retry-1",
    }
    with SessionLocal() as db:
        user = db.get(User, user_id)
        recurring_service.create(db, user, "basic")
    r = _post_webhook(
        client,
        {
            "Id": "sub-retry-1",
            "Amount": 199,
            "Currency": "RUB",
            "Status": "SUBSCRIPTION_ACTIVATED",
            "PaymentMethod": 6,
            "SubscriptionId": "sub-retry-1",
            "NextChargeAt": None,
        },
    )
    assert r.json()["result"] == "ok"

    payload = {
        "id": "charge-retry-1",
        "amount": 199,
        "currency": "RUB",
        "status": "CONFIRMED",
        "paymentmethod": 6,
        "subscriptionid": "sub-retry-1",
        "nextchargeat": None,
    }
    event = WebhookEvent(
        event_id="platega-charge:charge-retry-1:CONFIRMED",
        kind="sub.charge",
        provider="platega",
        payment_id="charge-retry-1",
        amount_kopecks=19900,
        currency="RUB",
        raw=payload,
    )
    with SessionLocal() as db:
        assert billing_webhook.claim_event(db, event)
        row = db.get(BillingEvent, event.event_id)
        row.received_at = utcnow() - dt.timedelta(minutes=15)
        db.commit()

    r = _post_webhook(
        client,
        {
            "Id": "charge-retry-1",
            "Amount": 199,
            "Currency": "RUB",
            "Status": "CONFIRMED",
            "PaymentMethod": 6,
            "SubscriptionId": "sub-retry-1",
            "NextChargeAt": None,
        },
    )
    assert r.json()["result"] == "duplicate"

    fake_api["routes"][("GET", "/transaction/charge-retry-1")] = {
        "id": "charge-retry-1",
        "status": "CONFIRMED",
        "paymentDetails": {"amount": 199, "currency": "RUB"},
    }
    with SessionLocal() as db:
        healed = recurring_service.retry_stuck(db)
    assert healed == 1

    with SessionLocal() as db:
        user = db.get(User, user_id)
        plan = db.scalar(select(Plan).where(Plan.code == "basic"))
        assert (user.active_subscription().expires_at - expires_before).days == plan.period_days
        row = db.get(BillingEvent, event.event_id)
        assert row.result == billing_webhook.OK

    with SessionLocal() as db:
        assert recurring_service.retry_stuck(db) == 0


def test_second_positive_payment_for_order_is_rejected_by_index(client, fake_api):
    order_id = _order_for(client, fake_api, "audit-unique@example.com", "tx-uniq-1")
    _pay_order(client, fake_api, order_id, "tx-uniq-1", 199)

    with SessionLocal() as db:
        original = db.scalar(select(Payment).where(Payment.order_id == order_id))
        assert original is not None

    with SessionLocal() as db:
        db.add(
            Payment(
                user_id=original.user_id,
                order_id=order_id,
                amount=199,
                currency="RUB",
                method="platega",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(
            Payment(
                user_id=original.user_id,
                order_id=order_id,
                amount=-199,
                currency="RUB",
                method="platega",
            )
        )
        db.commit()
