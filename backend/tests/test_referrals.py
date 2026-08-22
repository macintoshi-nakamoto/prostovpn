"""
Приглашения: за переход и за первую оплату.

Проверяется то, что стоит денег и доверия: бонус приходит один раз,
накрутить его повторным переходом нельзя, за себя дни не начисляются, а
подаренные дни не превращаются в выручку.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Payment, Referral, Subscription, User, utcnow
from app.services import referrals as referrals_service

INVITER_TG = 900_000_001
INVITED_TG = 900_000_002
STRANGER_TG = 900_000_003


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


def _make_user(client, auth, login: str, telegram_id: int | None = None) -> int:
    r = client.post(
        "/api/admin/users",
        json={"login": login, "password": "secret-123", "planCode": "basic"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"] if "id" in r.json() else r.json()["user"]["id"]
    if telegram_id:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            user.telegram_id = telegram_id
            db.commit()
    return user_id


def _access_until(user_id: int):
    with SessionLocal() as db:
        return db.get(User, user_id).access_expires_at(utcnow())


def test_join_bonus_is_granted_once(client, auth):
    inviter_id = _make_user(client, auth, "ref_inviter_a", INVITER_TG)
    before = _access_until(inviter_id)

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": INVITER_TG, "invited_telegram_id": INVITED_TG},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["invited"] == 1
    assert body["days"] == 2

    after = _access_until(inviter_id)
    assert (after - before).days == 2, "за переход по ссылке дарим ровно два дня"

    # Повторный переход того же человека — не второй бонус.
    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": INVITER_TG, "invited_telegram_id": INVITED_TG},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    assert _access_until(inviter_id) == after

    # Чужой человек не может «перехватить» уже приглашённого.
    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": STRANGER_TG, "invited_telegram_id": INVITED_TG},
        headers=auth,
    )
    assert r.status_code == 400

    # Бонусные дни — не деньги: платежей не появилось.
    with SessionLocal() as db:
        assert list(db.scalars(select(Payment).where(Payment.user_id == inviter_id))) == []


def test_self_invite_is_rejected(client, auth):
    _make_user(client, auth, "ref_selfie", 900_000_010)
    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": 900_000_010, "invited_telegram_id": 900_000_010},
        headers=auth,
    )
    assert r.status_code == 400
    assert "свое" in r.json()["detail"].lower() or "свои" in r.json()["detail"].lower()


def test_purchase_bonus_on_first_payment(client, auth):
    inviter_id = _make_user(client, auth, "ref_inviter_b", 900_000_020)
    invited_tg = 900_000_021

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": 900_000_020, "invited_telegram_id": invited_tg},
        headers=auth,
    )
    assert r.status_code == 201
    after_join = _access_until(inviter_id)

    # Приглашённый завёл учётку и оплатил.
    invited_id = _make_user(client, auth, "ref_invited_b", invited_tg)
    with SessionLocal() as db:
        invited = db.get(User, invited_id)
        assert referrals_service.credit_purchase(db, invited) is True

    after_purchase = _access_until(inviter_id)
    assert (after_purchase - after_join).days == 5, "за оплату приглашённого дарим пять дней"

    # Второй платёж того же человека бонус не повторяет.
    with SessionLocal() as db:
        invited = db.get(User, invited_id)
        assert referrals_service.credit_purchase(db, invited) is False
    assert _access_until(inviter_id) == after_purchase


def test_bonus_waits_for_inviter_account(client, auth):
    """Пригласивший без учётки получает дни, когда войдёт."""
    inviter_tg = 900_000_030
    invited_tg = 900_000_031

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": inviter_tg, "invited_telegram_id": invited_tg},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["pending"] == 1, "бонус висит неначисленным"

    inviter_id = _make_user(client, auth, "ref_late", None)
    before = _access_until(inviter_id)

    r = client.post(
        "/api/admin/referrals/link",
        json={"telegram_id": inviter_tg, "login": "ref_late"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pending"] == 0
    assert (_access_until(inviter_id) - before).days == 2


def test_bonus_days_do_not_enter_expected_revenue(client, auth):
    """Подаренные дни не считаются будущей выручкой."""
    from app.services import billing

    user_id = _make_user(client, auth, "ref_revenue", 900_000_040)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        # Снимаем все живые периоды: бонус ляжет отдельной строкой.
        for sub in db.scalars(select(Subscription).where(Subscription.user_id == user_id)):
            sub.is_cancelled = True
        db.commit()
        billing.add_bonus_days(db, user, 30, "тест")

    with SessionLocal() as db:
        bonus = db.scalar(
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.is_cancelled.is_(False))
            .order_by(Subscription.id.desc())
        )
        assert bonus is not None
        assert float(bonus.price) == 0.0
        assert bonus.auto_renew is False, "от подарка продления не ждём"

        import datetime as dt

        start = dt.datetime.combine(utcnow().date(), dt.time.min)
        _total, by_day = billing._expected_between(db, start, start + dt.timedelta(days=400))
        ids = {row["user_id"] for rows in by_day.values() for row in rows}
        assert user_id not in ids


def test_referral_survives_missing_inviter(client, auth):
    """Приглашение без учётки пригласившего не роняет выдачу приглашённого."""
    invited_id = _make_user(client, auth, "ref_orphan", 900_000_051)
    with SessionLocal() as db:
        db.add(
            Referral(
                inviter_telegram_id=900_000_050,
                invited_telegram_id=900_000_051,
                invited_user_id=invited_id,
            )
        )
        db.commit()
        invited = db.get(User, invited_id)
        assert referrals_service.credit_purchase(db, invited) is False
