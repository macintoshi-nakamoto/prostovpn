"""
Перевод дней и посуточная покупка.

Главное обещание перевода: сумма дней у двоих не меняется. Всё остальное —
защита от того, чтобы дни не появились из воздуха и не пропали в пути.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import DayTransfer, Order, Payment, Plan, User, utcnow
from app.services import transfers as transfers_service


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


def _make_user(client, auth, login: str, plan: str = "basic") -> int:
    r = client.post(
        "/api/admin/users",
        json={"login": login, "password": "secret-123", "planCode": plan},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["id"] if "id" in body else body["user"]["id"]


def _token(client, login: str) -> str:
    r = client.post("/api/v1/login", json={"login": login, "password": "secret-123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _days_left(user_id: int) -> int:
    with SessionLocal() as db:
        return db.get(User, user_id).access_days_left(utcnow()) or 0


def test_transfer_moves_days_between_accounts(client, auth):
    """Дни уходят у одного и приходят другому — ровно столько же."""
    sender_id = _make_user(client, auth, "tr_sender")
    recipient_id = _make_user(client, auth, "tr_recipient")

    before_sender = _days_left(sender_id)
    before_recipient = _days_left(recipient_id)
    assert before_sender >= 7

    token = _token(client, "tr_sender")
    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_recipient", "days": 7, "note": "держи"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["direction"] == "sent"
    assert r.json()["days"] == 7

    assert _days_left(sender_id) == before_sender - 7
    assert _days_left(recipient_id) == before_recipient + 7

    # Перевод — не выручка: платежей он не создаёт.
    with SessionLocal() as db:
        assert list(db.scalars(select(Payment).where(Payment.user_id == sender_id))) == []

    # История видна обеим сторонам, каждой со своей стороны.
    mine = client.get(
        "/api/v1/account/transfers", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert mine[0]["direction"] == "sent"

    other = _token(client, "tr_recipient")
    theirs = client.get(
        "/api/v1/account/transfers", headers={"Authorization": f"Bearer {other}"}
    ).json()
    assert theirs[0]["direction"] == "received"
    assert theirs[0]["days"] == 7
    # В истории — публичный идентификатор, а не чужой логин.
    assert theirs[0]["counterpart"].startswith("PV-")


def test_transfer_cannot_exceed_own_days(client, auth):
    """Больше, чем есть, отдать нельзя — и ничего при этом не меняется."""
    sender_id = _make_user(client, auth, "tr_greedy")
    _make_user(client, auth, "tr_greedy_friend")
    before = _days_left(sender_id)

    token = _token(client, "tr_greedy")
    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_greedy_friend", "days": before + 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "больше передать нельзя" in r.json()["detail"]
    assert _days_left(sender_id) == before


def test_transfer_rejects_self_and_unknown(client, auth):
    _make_user(client, auth, "tr_alone")
    token = _token(client, "tr_alone")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/account/transfers", json={"recipient": "tr_alone", "days": 1}, headers=headers
    )
    assert r.status_code == 400
    assert "самому себе" in r.json()["detail"]

    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": "нет-такого-логина", "days": 1},
        headers=headers,
    )
    assert r.status_code == 400
    assert "такого аккаунта нет" in r.json()["detail"]


def test_transfer_finds_recipient_by_public_id(client, auth):
    """Друга можно назвать публичным номером — его видно в кабинете."""
    sender_id = _make_user(client, auth, "tr_by_id_sender")
    recipient_id = _make_user(client, auth, "tr_by_id_recipient")
    with SessionLocal() as db:
        public_id = db.get(User, recipient_id).public_id

    before = _days_left(recipient_id)
    token = _token(client, "tr_by_id_sender")
    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": public_id.lower(), "days": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert _days_left(recipient_id) == before + 2


def test_admin_sees_transfers(client, auth):
    """Переводы видно в панели — и все, и по одному человеку."""
    sender_id = _make_user(client, auth, "tr_admin_view")
    _make_user(client, auth, "tr_admin_friend")
    token = _token(client, "tr_admin_view")
    client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_admin_friend", "days": 3},
        headers={"Authorization": f"Bearer {token}"},
    )

    rows = client.get("/api/admin/transfers", headers=auth).json()
    assert any(r["fromLogin"] == "tr_admin_view" and r["days"] == 3 for r in rows)

    mine = client.get(f"/api/admin/transfers?user_id={sender_id}", headers=auth).json()
    assert mine and all(
        r["fromId"] == sender_id or r["toId"] == sender_id for r in mine
    )


# --- посуточная покупка -------------------------------------------------------


def test_daily_plan_multiplies_price_and_days(client, auth):
    """Десять дней по десять рублей — сто рублей и десять дней доступа."""
    user_id = _make_user(client, auth, "tr_daily", plan="trial")
    token = _token(client, "tr_daily")

    r = client.post(
        "/api/v1/account/renew",
        json={"plan_code": "daily", "quantity": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["amount_kopecks"] == 10_000, "10 дней × 10 ₽"

    with SessionLocal() as db:
        from app.services import fulfil

        fulfil(db, db.get(Order, order["id"]))

    # Оплаченный период вступает сразу и снимает остаток пробного, поэтому
    # считаем не прибавку, а сам срок: десять купленных дней с этой минуты
    # (девять — то же самое после округления вниз неполных суток).
    assert _days_left(user_id) in (9, 10)

    with SessionLocal() as db:
        order_row = db.get(Order, order["id"])
        assert order_row.quantity == 10
        assert order_row.plan_code == "daily"


def test_daily_quantity_is_bounded(client, auth):
    """Опечатка в количестве не превращается в заказ на годы вперёд."""
    _make_user(client, auth, "tr_daily_typo", plan="trial")
    token = _token(client, "tr_daily_typo")

    r = client.post(
        "/api/v1/account/renew",
        json={"plan_code": "daily", "quantity": 9999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "не больше" in r.json()["detail"]


def test_quantity_ignored_for_regular_plans(client, auth):
    """У обычного тарифа срок в самом тарифе — количество его не множит."""
    _make_user(client, auth, "tr_qty_regular", plan="trial")
    token = _token(client, "tr_qty_regular")

    r = client.post(
        "/api/v1/account/renew",
        json={"plan_code": "basic", "quantity": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["amount_kopecks"] == 19_900, "пятикратной цены месяца быть не должно"
