from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Payment, User, utcnow
from app.services import billing


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_user(client, auth, login: str) -> int:
    r = client.post(
        "/api/admin/users",
        json={"login": login, "password": "secret-123", "planCode": "basic"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()["user"]["id"] if "user" in r.json() else r.json()["id"]


def test_free_flag_toggles_and_shows(client, auth):
    user_id = _make_user(client, auth, "free_flag_a")

    r = client.patch(f"/api/admin/users/{user_id}", json={"isFree": True}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["isFree"] is True

    r = client.patch(f"/api/admin/users/{user_id}", json={"isFree": False}, headers=auth)
    assert r.json()["isFree"] is False


def test_free_user_extension_writes_no_payment(client, auth):
    user_id = _make_user(client, auth, "free_flag_b")
    client.patch(f"/api/admin/users/{user_id}", json={"isFree": True}, headers=auth)

    r = client.post(
        f"/api/admin/users/{user_id}/extend",
        json={"planCode": "basic", "registerPayment": True},
        headers=auth,
    )
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        rows = list(db.scalars(select(Payment).where(Payment.user_id == user_id)))
        assert rows == [], "продление бесплатника не должно писать платёж"

    client.patch(f"/api/admin/users/{user_id}", json={"isFree": False}, headers=auth)
    r = client.post(
        f"/api/admin/users/{user_id}/extend",
        json={"planCode": "basic", "registerPayment": True},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        rows = list(db.scalars(select(Payment).where(Payment.user_id == user_id)))
        assert len(rows) == 1


def test_free_user_is_not_expected_revenue(client, auth):
    user_id = _make_user(client, auth, "free_flag_c")
    r = client.post(
        f"/api/admin/users/{user_id}/extend",
        json={"planCode": "basic", "registerPayment": False},
        headers=auth,
    )
    assert r.status_code == 200, r.text

    def expected_user_ids() -> set[int]:
        with SessionLocal() as db:
            start = dt.datetime.combine(utcnow().date(), dt.time.min)
            _total, by_day = billing._expected_between(db, start, start + dt.timedelta(days=400))
            return {row["user_id"] for rows in by_day.values() for row in rows}

    assert user_id in expected_user_ids()

    client.patch(f"/api/admin/users/{user_id}", json={"isFree": True}, headers=auth)
    assert user_id not in expected_user_ids()
