from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    DeliveryJob,
    Order,
    OrderStatus,
    Payment,
    Plan,
    Provisioning,
    RecurringSub,
    Server,
    User,
)
from app.payments import platega
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


def _post_webhook(client, payload: dict, headers: dict | None = None):
    return client.post(
        WEBHOOK,
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or GOOD_HEADERS)},
    )


def _paid_user(client, fake_api, email: str) -> str:
    with SessionLocal() as db:
        plan = db.scalar(select(Plan).where(Plan.code == "basic"))
        amount = plan.price_kopecks / 100

    tx = f"tx-{email.split('@', maxsplit=1)[0]}"
    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": tx,
        "redirect": "https://pay.platega.io/?id=" + tx,
        "status": "PENDING",
    }
    fake_api["routes"][("GET", f"/transaction/{tx}")] = {
        "id": tx,
        "status": "CONFIRMED",
        "paymentDetails": {"amount": amount, "currency": "RUB"},
    }

    from app.services import create_order

    with SessionLocal() as db:
        order = create_order(db, plan_code="basic", email=email, provider_name="platega")
        order_id = order.id
        assert order.redirect_url and tx in order.redirect_url

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
    assert r.json()["result"] == "ok"

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        assert order.status == OrderStatus.PAID.value
        assert order.user_id
    return order_id


def test_webhook_without_secret_is_rejected(client):
    r = _post_webhook(
        client,
        {"id": "x", "status": "CONFIRMED", "amount": 1},
        headers={"X-MerchantId": MERCHANT, "X-Secret": "wrong"},
    )
    assert r.status_code == 403


def test_webhook_subscription_event_without_secret_is_rejected(client):
    r = _post_webhook(
        client,
        {"Id": "s", "Status": "SUBSCRIPTION_ACTIVATED", "SubscriptionId": "s"},
        headers={"X-MerchantId": "not-us", "X-Secret": SECRET},
    )
    assert r.status_code == 403


def test_confirmed_payment_grants_access_once(client, fake_api):
    order_id = _paid_user(client, fake_api, "platega-once@example.com")

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        tx = order.provider_payment_id
        amount = order.amount_kopecks / 100
        user_id = order.user_id

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
    assert r.json()["result"] == "duplicate"

    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.id == user_id)))
        assert len(users) == 1
        payments_rows = list(db.scalars(select(Payment).where(Payment.order_id == order_id)))
        assert len(payments_rows) == 1


def test_overpayment_grants_access(client, fake_api):
    email = "platega-over@example.com"
    tx = "tx-over"
    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": tx,
        "redirect": "https://pay.platega.io/?id=" + tx,
    }
    fake_api["routes"][("GET", f"/transaction/{tx}")] = {
        "id": tx,
        "status": "CONFIRMED",
        "paymentDetails": {"amount": 10.80, "currency": "RUB"},
    }

    from app.services import create_order

    with SessionLocal() as db:
        order = create_order(db, plan_code="daily", email=email, provider_name="platega")
        order_id = order.id
        assert order.amount_kopecks == 1000

    r = _post_webhook(
        client,
        {
            "id": tx,
            "amount": 10.80,
            "currency": "RUB",
            "status": "CONFIRMED",
            "paymentMethod": 2,
            "payload": order_id,
        },
    )
    assert r.status_code == 200
    assert r.json()["result"] == "ok"

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        assert order.status == OrderStatus.PAID.value
        assert order.subscription_id is not None


def test_amount_mismatch_does_not_grant(client, fake_api):
    email = "platega-mismatch@example.com"
    tx = "tx-mismatch"
    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": tx,
        "redirect": "https://pay.platega.io/?id=" + tx,
    }
    fake_api["routes"][("GET", f"/transaction/{tx}")] = {
        "id": tx,
        "status": "CONFIRMED",
        "paymentDetails": {"amount": 1, "currency": "RUB"},
    }

    from app.services import create_order

    with SessionLocal() as db:
        order = create_order(db, plan_code="basic", email=email, provider_name="platega")
        order_id = order.id

    r = _post_webhook(
        client,
        {
            "id": tx,
            "amount": 1,
            "currency": "RUB",
            "status": "CONFIRMED",
            "paymentMethod": 2,
            "payload": order_id,
        },
    )
    assert r.status_code == 200
    assert r.json()["result"] == "amount_mismatch"

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        assert order.status == OrderStatus.FAILED.value
        assert order.user_id is None


def _live_sub(db, user_id: int) -> RecurringSub:
    return db.scalar(
        select(RecurringSub)
        .where(RecurringSub.user_id == user_id)
        .order_by(RecurringSub.id.desc())
    )


def test_subscription_lifecycle(client, fake_api):
    order_id = _paid_user(client, fake_api, "platega-sub@example.com")
    with SessionLocal() as db:
        user_id = db.get(Order, order_id).user_id
        plan = db.scalar(select(Plan).where(Plan.code == "basic"))
        amount = plan.price_kopecks / 100
        expires_before = db.get(User, user_id).active_subscription().expires_at

    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": "sub-1",
        "redirect": "https://pay.platega.io/subscription/sub-1",
    }
    with SessionLocal() as db:
        user = db.get(User, user_id)
        sub = recurring_service.create(db, user, "basic")
        assert sub.status == "pending"
        assert sub.interval == "month"

    with SessionLocal() as db:
        user = db.get(User, user_id)
        sub = recurring_service.create(db, user, "basic")
        assert sub.status == "pending"

    r = _post_webhook(
        client,
        {
            "Id": "sub-1",
            "Amount": amount,
            "Currency": "RUB",
            "Status": "SUBSCRIPTION_ACTIVATED",
            "PaymentMethod": 6,
            "SubscriptionId": "sub-1",
            "NextChargeAt": "2026-09-22T10:00:00Z",
        },
    )
    assert r.json()["result"] == "ok"
    with SessionLocal() as db:
        sub = _live_sub(db, user_id)
        assert sub.status == "active"
        assert sub.next_charge_at is not None
        on_jobs = list(
            db.scalars(select(DeliveryJob).where(DeliveryJob.template == "recurring_on"))
        )
        assert on_jobs, "письмо о подключении должно встать в очередь"

    fake_api["routes"][("GET", "/transaction/charge-1")] = {
        "id": "charge-1",
        "status": "CONFIRMED",
        "paymentDetails": {"amount": amount, "currency": "RUB"},
    }
    charge = {
        "Id": "charge-1",
        "Amount": amount,
        "Currency": "RUB",
        "Status": "CONFIRMED",
        "PaymentMethod": 6,
        "SubscriptionId": "sub-1",
        "NextChargeAt": "2026-10-22T10:00:00Z",
    }
    r = _post_webhook(client, charge)
    assert r.json()["result"] == "ok"

    with SessionLocal() as db:
        user = db.get(User, user_id)
        expires_after = user.active_subscription().expires_at
        assert (expires_after - expires_before).days == plan.period_days
        order = db.scalar(select(Order).where(Order.provider_payment_id == "charge-1"))
        assert order is not None
        assert order.status == OrderStatus.PAID.value
        assert order.origin == "recurring"

    r = _post_webhook(client, charge)
    assert r.json()["result"] == "duplicate"
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.active_subscription().expires_at == expires_after

    fake_api["routes"][("GET", "/transaction/charge-2")] = {
        "id": "charge-2",
        "status": "CONFIRMED",
        "paymentDetails": {"amount": 1, "currency": "RUB"},
    }
    bad = dict(charge, Id="charge-2", Amount=1)
    r = _post_webhook(client, bad)
    assert r.json()["result"] == "amount_mismatch"
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.active_subscription().expires_at == expires_after

    failed = dict(charge, Id="charge-3", Status="CANCELED", NextChargeAt=None)
    r = _post_webhook(client, failed)
    assert r.json()["result"] == "ok"
    with SessionLocal() as db:
        sub = _live_sub(db, user_id)
        assert sub.status == "past_due"
        fail_jobs = list(
            db.scalars(select(DeliveryJob).where(DeliveryJob.template == "recurring_failed"))
        )
        assert fail_jobs

    fake_api["routes"][("POST", "/subscription/sub-1/cancel")] = {
        "subscriptionId": "sub-1",
        "status": "cancelled",
    }
    with SessionLocal() as db:
        user = db.get(User, user_id)
        sub = recurring_service.get_live(db, user)
        recurring_service.cancel(db, sub)
    with SessionLocal() as db:
        sub = _live_sub(db, user_id)
        assert sub.status == "cancelled"
        assert recurring_service.get_live(db, db.get(User, user_id)) is None


def test_charge_for_unknown_subscription_is_kept_for_admin(client, fake_api):
    r = _post_webhook(
        client,
        {
            "Id": "charge-x",
            "Amount": 100,
            "Currency": "RUB",
            "Status": "CONFIRMED",
            "PaymentMethod": 6,
            "SubscriptionId": "no-such-sub",
            "NextChargeAt": None,
        },
    )
    assert r.status_code == 200
    assert r.json()["result"] == "unknown_sub"


def test_pending_order_with_live_link_is_reused(client, fake_api):
    order_id = _paid_user(client, fake_api, "platega-reuse@example.com")
    with SessionLocal() as db:
        user_id = db.get(Order, order_id).user_id

    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": "tx-reuse-1",
        "redirect": "https://pay.platega.io/?id=tx-reuse-1",
        "expiresIn": "00:30:00",
    }

    from app.services import create_order_for_user

    with SessionLocal() as db:
        user = db.get(User, user_id)
        first = create_order_for_user(db, user, "basic", provider_name="platega")
        first_id = first.id
        assert first.link_expires_at is not None

    calls_before = len(fake_api["calls"])
    with SessionLocal() as db:
        user = db.get(User, user_id)
        second = create_order_for_user(db, user, "basic", provider_name="platega")
        assert second.id == first_id
    assert len(fake_api["calls"]) == calls_before

    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": "tx-reuse-year",
        "redirect": "https://pay.platega.io/?id=tx-reuse-year",
        "expiresIn": "00:30:00",
    }
    with SessionLocal() as db:
        user = db.get(User, user_id)
        other = create_order_for_user(db, user, "year", provider_name="platega")
        assert other.id != first_id

    import datetime as _dt

    from app.models import utcnow as _utcnow

    with SessionLocal() as db:
        stale = db.get(Order, first_id)
        stale.link_expires_at = _utcnow() - _dt.timedelta(minutes=1)
        db.commit()

    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": "tx-reuse-2",
        "redirect": "https://pay.platega.io/?id=tx-reuse-2",
        "expiresIn": "00:30:00",
    }
    with SessionLocal() as db:
        user = db.get(User, user_id)
        third = create_order_for_user(db, user, "basic", provider_name="platega")
        assert third.id != first_id
        assert third.provider_payment_id == "tx-reuse-2"


def test_recurring_pending_link_is_reused(client, fake_api):
    order_id = _paid_user(client, fake_api, "platega-rec-reuse@example.com")
    with SessionLocal() as db:
        user_id = db.get(Order, order_id).user_id

    fake_api["routes"][("POST", "/transaction/process")] = {
        "transactionId": "sub-reuse-1",
        "redirect": "https://pay.platega.io/subscription/sub-reuse-1",
    }
    with SessionLocal() as db:
        user = db.get(User, user_id)
        first = recurring_service.create(db, user, "basic")
        first_id = first.id

    calls_before = len(fake_api["calls"])
    with SessionLocal() as db:
        user = db.get(User, user_id)
        second = recurring_service.create(db, user, "basic")
        assert second.id == first_id
    assert len(fake_api["calls"]) == calls_before


def test_payment_method_reaches_platega_and_splits_orders(client, fake_api):
    order_id = _paid_user(client, fake_api, "platega-method@example.com")
    with SessionLocal() as db:
        user_id = db.get(Order, order_id).user_id

    from app.services import create_order_for_user

    def _route(tx: str) -> None:
        fake_api["routes"][("POST", "/transaction/process")] = {
            "transactionId": tx,
            "redirect": f"https://pay.platega.io/?id={tx}",
            "expiresIn": "00:30:00",
        }

    _route("tx-method-crypto")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        crypto_order = create_order_for_user(
            db, user, "basic", provider_name="platega", payment_method="crypto"
        )
        crypto_id = crypto_order.id
        assert crypto_order.payment_method == "crypto"
    assert fake_api["calls"][-1][2]["paymentMethod"] == platega.METHODS["crypto"] == 13

    _route("tx-method-sbp")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        sbp_order = create_order_for_user(
            db, user, "basic", provider_name="platega", payment_method="sbp"
        )
        assert sbp_order.id != crypto_id
        assert sbp_order.payment_method == "sbp"
    assert fake_api["calls"][-1][2]["paymentMethod"] == 2

    calls_before = len(fake_api["calls"])
    with SessionLocal() as db:
        user = db.get(User, user_id)
        again = create_order_for_user(
            db, user, "basic", provider_name="platega", payment_method="crypto"
        )
        assert again.id == crypto_id
    assert len(fake_api["calls"]) == calls_before

    _route("tx-method-junk")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        junk = create_order_for_user(
            db, user, "year", provider_name="platega", payment_method="dogecoin"
        )
        assert junk.payment_method is None
    assert fake_api["calls"][-1][2]["paymentMethod"] == settings().platega_payment_method


def test_external_purchase_becomes_refundable_order(client, fake_api):
    from decimal import Decimal

    from app.models import Payment, Plan
    from app.services import add_payment, grant_subscription
    from app.services import orders as orders_service

    order_id = _paid_user(client, fake_api, "stars-order@example.com")
    with SessionLocal() as db:
        user_id = db.get(Order, order_id).user_id

    with SessionLocal() as db:
        user = db.get(User, user_id)
        plan = db.scalar(select(Plan).where(Plan.code == "basic"))
        rub = plan.price_kopecks / 100

        sub = grant_subscription(db, user, days=plan.period_days, plan=plan, price=rub)
        star_order = orders_service.record_paid_order(
            db,
            user,
            plan,
            provider="telegram",
            payment_method="stars",
            external_id="charge-test-1",
            amount_kopecks=plan.price_kopecks,
            subscription_id=sub.id,
        )
        assert star_order is not None
        assert star_order.status == "paid"
        assert star_order.provider == "telegram"
        assert star_order.payment_method == "stars"
        star_order_id = star_order.id

        payment = add_payment(
            db,
            amount=rub,
            user=user,
            method="Telegram Stars",
            comment="Продление",
            subscription_id=sub.id,
            external_id="charge-test-1",
            order_id=star_order_id,
        )
        assert payment.order_id == star_order_id

        twin = orders_service.record_paid_order(
            db,
            user,
            plan,
            provider="telegram",
            payment_method="stars",
            external_id="charge-test-1",
            amount_kopecks=plan.price_kopecks,
            subscription_id=sub.id,
        )
        assert twin is None

    with SessionLocal() as db:
        orders_service.refund(db, db.get(Order, star_order_id), reason="возврат звёзд")

    with SessionLocal() as db:
        refunded = db.get(Order, star_order_id)
        assert refunded.status == "refunded"
        rows = list(db.scalars(select(Payment).where(Payment.order_id == star_order_id)))
        assert sum(row.amount for row in rows) == Decimal("0.00")
