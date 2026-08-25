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

    with SessionLocal() as db:
        assert list(db.scalars(select(Payment).where(Payment.user_id == sender_id))) == []

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
    assert theirs[0]["counterpart"].startswith("PV-")


def test_transfer_cannot_exceed_own_days(client, auth):
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


def test_daily_plan_multiplies_price_and_days(client, auth):
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

    assert _days_left(user_id) in (9, 10)

    with SessionLocal() as db:
        order_row = db.get(Order, order["id"])
        assert order_row.quantity == 10
        assert order_row.plan_code == "daily"


def test_daily_quantity_is_bounded(client, auth):
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
    _make_user(client, auth, "tr_qty_regular", plan="trial")
    token = _token(client, "tr_qty_regular")

    with SessionLocal() as db:
        price = db.scalar(select(Plan).where(Plan.code == "basic")).price_kopecks

    r = client.post(
        "/api/v1/account/renew",
        json={"plan_code": "basic", "quantity": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["amount_kopecks"] == price, "пятикратной цены месяца быть не должно"


def test_transfer_cannot_mint_days_from_queue(client, auth):
    from app.services import grant_subscription

    sender_id = _make_user(client, auth, "tr_mint_sender")
    recipient_id = _make_user(client, auth, "tr_mint_recipient")

    with SessionLocal() as db:
        grant_subscription(db, db.get(User, sender_id), days=5, plan="daily", price=50.0)

    before_sender = _days_left(sender_id)
    before_recipient = _days_left(recipient_id)
    assert before_sender > 30, "в очереди должны быть оба периода"

    token = _token(client, "tr_mint_sender")
    move = before_sender - 2
    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_mint_recipient", "days": move},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text

    after_sender = _days_left(sender_id)
    after_recipient = _days_left(recipient_id)

    assert before_sender - after_sender == move, "у отправителя списали не столько"
    assert after_recipient - before_recipient == move, "получателю начислили не столько"
    assert (after_sender + after_recipient) == (before_sender + before_recipient)


def test_transfer_of_everything_leaves_nothing(client, auth):
    sender_id = _make_user(client, auth, "tr_all_sender")
    _make_user(client, auth, "tr_all_recipient")

    everything = _days_left(sender_id)
    token = _token(client, "tr_all_sender")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_all_recipient", "days": everything},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert _days_left(sender_id) == 0

    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_all_recipient", "days": everything},
        headers=headers,
    )
    assert r.status_code == 400
    assert _days_left(sender_id) == 0


def test_received_days_survive_first_purchase(client, auth):
    from app.services import grant_subscription

    sender_id = _make_user(client, auth, "tr_keep_sender")
    recipient_id = _make_user(client, auth, "tr_keep_recipient", plan="trial")

    token = _token(client, "tr_keep_sender")
    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_keep_recipient", "days": 20},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    with_gift = _days_left(recipient_id)
    assert with_gift >= 20

    with SessionLocal() as db:
        grant_subscription(db, db.get(User, recipient_id), days=30, plan="basic", price=199.0)

    after_purchase = _days_left(recipient_id)
    assert after_purchase >= 49, f"подарок сгорел: было {with_gift}, стало {after_purchase}"


def test_recipient_lookup_ignores_like_wildcards(client, auth):
    _make_user(client, auth, "tr_wild_sender")
    _make_user(client, auth, "tr_wild_target")

    token = _token(client, "tr_wild_sender")
    for needle in ("%", "tr_wild_%", "tr_wild_targe_"):
        r = client.post(
            "/api/v1/account/transfers",
            json={"recipient": needle, "days": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400, f"«{needle}» нашёл получателя: {r.text}"
        assert "такого аккаунта нет" in r.json()["detail"]


def test_refund_claws_back_transferred_days(client, auth):
    from app.models import Order, OrderStatus
    from app.services import grant_subscription, refund

    buyer_id = _make_user(client, auth, "tr_cheat_buyer", plan="trial")
    friend_id = _make_user(client, auth, "tr_cheat_friend", plan="trial")

    with SessionLocal() as db:
        buyer = db.get(User, buyer_id)
        sub = grant_subscription(db, buyer, days=30, plan="basic", price=199.0)
        order = Order(
            plan_code="basic",
            email="cheat-transfer@example.com",
            amount_kopecks=19900,
            currency="RUB",
            status=OrderStatus.PAID.value,
            provider="platega",
            user_id=buyer_id,
            subscription_id=sub.id,
        )
        db.add(order)
        db.commit()
        order_id = order.id

    token = _token(client, "tr_cheat_buyer")
    everything = _days_left(buyer_id)
    r = client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_cheat_friend", "days": everything},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    friend_after_gift = _days_left(friend_id)

    with SessionLocal() as db:
        refund(db, db.get(Order, order_id), reason="чарджбек")

    friend_after_refund = _days_left(friend_id)
    assert friend_after_refund < friend_after_gift, "дни остались у друга после возврата"

    with SessionLocal() as db:
        moved = db.scalar(
            select(DayTransfer).where(DayTransfer.from_user_id == buyer_id)
        )
        assert moved.reverted_days > 0, "отзыв не отмечен в переводе"


def test_bot_transfer_is_marked_and_limited(client, auth):
    sender_id = _make_user(client, auth, "tr_bot_sender")
    _make_user(client, auth, "tr_bot_friend")

    r = client.post(
        "/api/admin/transfers",
        json={
            "fromUserId": sender_id,
            "recipient": "tr_bot_friend",
            "days": 1,
            "origin": "bot",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    assert r.json()["origin"] == "bot", "перевод из Telegram не должен выглядеть ручным"

    r = client.post(
        "/api/admin/transfers",
        json={"fromUserId": sender_id, "recipient": "tr_bot_friend", "days": 1},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    assert r.json()["origin"] == "panel"


def test_admin_transfers_filter_by_user(client, auth):
    a_id = _make_user(client, auth, "tr_filter_a")
    b_id = _make_user(client, auth, "tr_filter_b")
    _make_user(client, auth, "tr_filter_c")

    token = _token(client, "tr_filter_a")
    client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_filter_b", "days": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    other = _token(client, "tr_filter_c")
    client.post(
        "/api/v1/account/transfers",
        json={"recipient": "tr_filter_b", "days": 3},
        headers={"Authorization": f"Bearer {other}"},
    )

    rows = client.get(f"/api/admin/transfers?user_id={a_id}", headers=auth).json()
    assert rows, "переводы этого клиента должны найтись"
    assert all(
        row["fromId"] == a_id or row["toId"] == a_id for row in rows
    ), "в карточку попали чужие переводы"

    both = client.get(f"/api/admin/transfers?user_id={b_id}", headers=auth).json()
    assert len(both) >= 2
