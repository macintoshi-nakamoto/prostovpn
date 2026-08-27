from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    Order,
    Provisioning,
    Server,
    Subscription,
    SubscriptionFreeze,
    User,
)
from app.payments import mock as mock_provider


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


def _paid_user(client, email: str) -> dict:
    r = client.post("/api/v1/orders", json={"plan_code": "basic", "email": email})
    assert r.status_code == 201, r.text
    order = r.json()
    with SessionLocal() as db:
        body = mock_provider.build_payload(db.get(Order, order["id"]), "succeeded", 1)
    r = client.post(
        "/api/v1/billing/webhook/mock",
        content=body,
        headers={
            mock_provider.SIGNATURE_HEADER: mock_provider.sign(body),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    return client.get(f"/api/v1/orders/{order['id']}/status").json()


def _login(client, creds: dict, platform: str = "windows") -> dict:
    r = client.post(
        "/api/v1/login",
        json={
            "login": creds["login"],
            "password": creds["password"],
            "platform": platform,
            "device_id": "dev-1",
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_freeze_and_unfreeze_shift_expiry(client):
    creds = _paid_user(client, "freeze-basic@example.com")
    auth = _login(client, creds)

    account = client.get("/api/v1/account", headers=auth).json()
    assert account["frozen_at"] is None
    assert account["freezes_left"] == 2
    before = account["expires_at"]

    r = client.post("/api/v1/account/freeze", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["frozen_at"] is not None
    assert body["active"] is False
    assert body["freezes_left"] == 1

    # срок ещё не сдвинут — сдвиг происходит при разморозке
    assert body["expires_at"] == before

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == creds["login"]))
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
        # имитируем двое суток заморозки: вся история сдвигается в прошлое
        sub.starts_at -= dt.timedelta(days=2)
        sub.expires_at -= dt.timedelta(days=2)
        user.frozen_at -= dt.timedelta(days=2)
        db.commit()
        old_expiry = sub.expires_at

    r = client.post("/api/v1/account/unfreeze", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["frozen_at"] is None
    assert body["active"] is True

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == creds["login"]))
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
        shifted = sub.expires_at - old_expiry
        assert dt.timedelta(days=1, hours=23) < shifted < dt.timedelta(days=2, hours=1)
        row = db.scalar(select(SubscriptionFreeze).where(SubscriptionFreeze.user_id == user.id))
        assert row.ended_at is not None


def test_freeze_limit_two_per_month(client):
    creds = _paid_user(client, "freeze-limit@example.com")
    auth = _login(client, creds)

    for _ in range(2):
        assert client.post("/api/v1/account/freeze", headers=auth).status_code == 200
        assert client.post("/api/v1/account/unfreeze", headers=auth).status_code == 200

    r = client.post("/api/v1/account/freeze", headers=auth)
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "freeze_limit"
    assert client.get("/api/v1/account", headers=auth).json()["freezes_left"] == 0

    # в следующем месяце лимит обнуляется
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == creds["login"]))
        for row in db.scalars(
            select(SubscriptionFreeze).where(SubscriptionFreeze.user_id == user.id)
        ):
            row.started_at -= dt.timedelta(days=40)
        db.commit()
    assert client.post("/api/v1/account/freeze", headers=auth).status_code == 200
    assert client.post("/api/v1/account/unfreeze", headers=auth).status_code == 200


def test_freeze_requires_subscription_and_stops_access(client):
    r = client.post(
        "/api/v1/register",
        json={"login": "no-sub-freeze", "password": "pass-1234", "platform": "web"},
    )
    assert r.status_code == 201, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}

    # регистрация выдаёт пробные дни — гасим их, чтобы подписки не было
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == "no-sub-freeze"))
        for sub in db.scalars(select(Subscription).where(Subscription.user_id == user.id)):
            sub.expires_at = sub.starts_at
        db.commit()

    r = client.post("/api/v1/account/freeze", headers=auth)
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "no_subscription"


def test_frozen_login_gets_notice_and_no_servers(client):
    creds = _paid_user(client, "freeze-notice@example.com")
    auth = _login(client, creds)
    assert client.post("/api/v1/account/freeze", headers=auth).status_code == 200

    r = client.post(
        "/api/v1/login",
        json={
            "login": creds["login"],
            "password": creds["password"],
            "platform": "windows",
            "device_id": "dev-2",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["servers"] == []
    assert "заморожена" in (body["notice"] or "")

    auth2 = {"Authorization": f"Bearer {body['token']}"}
    assert client.post("/api/v1/account/unfreeze", headers=auth2).status_code == 200

    r = client.post("/api/v1/account/unfreeze", headers=auth2)
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "not_frozen"
