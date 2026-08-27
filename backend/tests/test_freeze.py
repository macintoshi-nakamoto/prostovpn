from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    EndpointKind,
    NodeEndpoint,
    Order,
    Provisioning,
    Server,
    Subscription,
    User,
)
from app.payments import mock as mock_provider
from app.services import xray


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
                    city="Амстердам",
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


def _login(client, creds: dict, platform: str = "windows", device: str = "dev-1") -> dict:
    r = client.post(
        "/api/v1/login",
        json={
            "login": creds["login"],
            "password": creds["password"],
            "platform": platform,
            "device_id": device,
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_freeze_pauses_and_resume_returns_days(client):
    creds = _paid_user(client, "freeze-basic@example.com")
    auth = _login(client, creds)

    account = client.get("/api/v1/account", headers=auth).json()
    assert account["freeze"]["frozen"] is False
    assert account["freeze"]["can_freeze"] is True
    assert account["freeze"]["month_left"] == 2

    r = client.post("/api/v1/account/freeze", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["freeze"]["frozen"] is True
    assert body["active"] is False
    assert body["freeze"]["month_left"] == 1

    # имитируем двое суток паузы: вся история уезжает в прошлое
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == creds["login"]))
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
        sub.starts_at -= dt.timedelta(days=3)
        sub.expires_at -= dt.timedelta(days=3)
        user.frozen_at -= dt.timedelta(days=2)
        db.commit()
        old_expiry = sub.expires_at

    shown = client.get("/api/v1/account", headers=auth).json()
    assert shown["freeze"]["frozen_days"] == 2

    r = client.post("/api/v1/account/resume", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["freeze"]["frozen"] is False
    assert body["active"] is True

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == creds["login"]))
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
        shifted = sub.expires_at - old_expiry
        assert dt.timedelta(days=1, hours=23) < shifted < dt.timedelta(days=2, hours=1)
        assert user.frozen_days_used == 2
        assert user.freeze_count == 1


def test_freeze_limit_two_per_calendar_month(client):
    creds = _paid_user(client, "freeze-limit@example.com")
    auth = _login(client, creds)

    for _ in range(2):
        assert client.post("/api/v1/account/freeze", headers=auth).status_code == 200
        assert client.post("/api/v1/account/resume", headers=auth).status_code == 200

    state = client.get("/api/v1/account", headers=auth).json()["freeze"]
    assert state["month_left"] == 0
    assert state["can_freeze"] is False
    assert "не чаще" in state["reason"]

    r = client.post("/api/v1/account/freeze", headers=auth)
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "freeze_forbidden"

    # новый месяц — лимит обнуляется
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == creds["login"]))
        user.freeze_month = "2000-01"
        db.commit()
    assert client.get("/api/v1/account", headers=auth).json()["freeze"]["month_left"] == 2
    assert client.post("/api/v1/account/freeze", headers=auth).status_code == 200
    assert client.post("/api/v1/account/resume", headers=auth).status_code == 200


def test_trial_days_cannot_be_frozen(client):
    r = client.post(
        "/api/v1/register",
        json={"login": "trial-freeze", "password": "pass-1234", "platform": "web"},
    )
    assert r.status_code == 201, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}

    state = client.get("/api/v1/account", headers=auth).json()["freeze"]
    if state["can_freeze"]:
        pytest.skip("регистрация выдала оплачиваемый тариф — пробного нет")
    r = client.post("/api/v1/account/freeze", headers=auth)
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "freeze_forbidden"


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
    assert "на паузе" in (body["notice"] or "")

    auth2 = {"Authorization": f"Bearer {body['token']}"}
    assert client.post("/api/v1/account/resume", headers=auth2).status_code == 200


def test_vless_identity_survives_reissue(client, monkeypatch):
    # Повторная выдача VLESS не меняет UUID и short_id: сохранённая ссылка
    # должна пережить заморозку и просрочку подписки.
    monkeypatch.setattr(xray, "push_to_node", lambda db, server: True)

    creds = _paid_user(client, "freeze-vless@example.com")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == creds["login"]))
        server = db.scalar(select(Server).limit(1))
        endpoint = db.scalar(select(NodeEndpoint).where(NodeEndpoint.kind == EndpointKind.VLESS))
        if endpoint is None:
            endpoint = NodeEndpoint(
                server_id=server.id,
                kind=EndpointKind.VLESS,
                transport="tcp",
                handle="vless0",
                listen_port=443,
                params={"short_ids": ["abcd1234"], "public_key": "pk"},
            )
            db.add(endpoint)
            db.commit()

        cred = xray.issue_cred(db, user, server, endpoint, device_id="dev-1")
        first_fp, first_extra = cred.identity_fp, dict(cred.extra or {})

        xray.revoke_for_user(db, user.id)
        cred = xray.issue_cred(db, user, server, endpoint, device_id="dev-1")
        assert cred.revoked_at is None
        assert cred.identity_fp == first_fp
        assert (cred.extra or {}).get("short_id") == first_extra.get("short_id")
