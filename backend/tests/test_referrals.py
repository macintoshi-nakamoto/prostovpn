from __future__ import annotations

import datetime as dt

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

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": INVITER_TG, "invited_telegram_id": INVITED_TG},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    assert _access_until(inviter_id) == after

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": STRANGER_TG, "invited_telegram_id": INVITED_TG},
        headers=auth,
    )
    assert r.status_code == 400

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

    invited_id = _make_user(client, auth, "ref_invited_b", invited_tg)
    with SessionLocal() as db:
        invited = db.get(User, invited_id)
        assert referrals_service.credit_purchase(db, invited) is True

    after_purchase = _access_until(inviter_id)
    assert (after_purchase - after_join).days == 5, "за оплату приглашённого дарим пять дней"

    with SessionLocal() as db:
        invited = db.get(User, invited_id)
        assert referrals_service.credit_purchase(db, invited) is False
    assert _access_until(inviter_id) == after_purchase


def test_bonus_waits_for_inviter_account(client, auth):
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
    from app.services import billing

    user_id = _make_user(client, auth, "ref_revenue", 900_000_040)
    with SessionLocal() as db:
        user = db.get(User, user_id)
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


def test_purchase_keeps_bonus_days(client, auth):
    from app.services import billing, grant_subscription

    user_id = _make_user(client, auth, "ref_carry", 900_000_060)
    with SessionLocal() as db:
        for sub in db.scalars(select(Subscription).where(Subscription.user_id == user_id)):
            sub.is_cancelled = True
        db.commit()
        user = db.get(User, user_id)
        billing.add_bonus_days(db, user, 6, "приглашения")

    before = _access_until(user_id)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        grant_subscription(db, user, days=30, plan="basic", price=199.0)

    after = _access_until(user_id)
    assert (after - before).days == 30, f"было {before}, стало {after}"

    with SessionLocal() as db:
        live = list(
            db.scalars(
                select(Subscription).where(
                    Subscription.user_id == user_id, Subscription.is_cancelled.is_(False)
                )
            )
        )
        assert len(live) == 1, "оплаченный период один, бонусный в него влился"
        assert float(live[0].price) == 199.0


def test_refund_keeps_bonus_days(client, auth):
    from app.services import billing, grant_subscription, refund
    from app.models import Order, OrderStatus

    user_id = _make_user(client, auth, "ref_refund_keep", 900_000_070)
    with SessionLocal() as db:
        for sub in db.scalars(select(Subscription).where(Subscription.user_id == user_id)):
            sub.is_cancelled = True
        db.commit()
        user = db.get(User, user_id)
        billing.add_bonus_days(db, user, 7, "приглашения")
        sub = grant_subscription(db, user, days=30, plan="basic", price=199.0)
        order = Order(
            plan_code="basic",
            email="ref-refund@example.com",
            amount_kopecks=19900,
            currency="RUB",
            status=OrderStatus.PAID.value,
            provider="platega",
            user_id=user_id,
            subscription_id=sub.id,
        )
        db.add(order)
        db.commit()
        order_id = order.id

    with SessionLocal() as db:
        refund(db, db.get(Order, order_id), reason="проверка")

    with SessionLocal() as db:
        user = db.get(User, user_id)
        left = (user.access_expires_at(utcnow()) - utcnow()).days if user.access_expires_at(utcnow()) else -1
        assert 5 <= left <= 7, f"подаренные дни должны остаться, осталось {left}"
        assert not user.is_blocked, "за возврат при живых подаренных днях не банят"


def test_refund_takes_back_referral_bonus(client, auth):
    from app.models import Order, OrderStatus
    from app.services import grant_subscription, refund

    inviter_id = _make_user(client, auth, "ref_cheater", 900_000_080)
    invited_tg = 900_000_081

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": 900_000_080, "invited_telegram_id": invited_tg},
        headers=auth,
    )
    assert r.status_code == 201

    invited_id = _make_user(client, auth, "ref_cheater_friend", invited_tg)
    with SessionLocal() as db:
        invited = db.get(User, invited_id)
        assert referrals_service.credit_purchase(db, invited) is True

    with_bonus = _access_until(inviter_id)

    with SessionLocal() as db:
        invited = db.get(User, invited_id)
        sub = grant_subscription(db, invited, days=30, plan="basic", price=199.0)
        order = Order(
            plan_code="basic",
            email="cheat@example.com",
            amount_kopecks=19900,
            currency="RUB",
            status=OrderStatus.PAID.value,
            provider="platega",
            user_id=invited_id,
            subscription_id=sub.id,
        )
        db.add(order)
        db.commit()
        order_id = order.id

    with SessionLocal() as db:
        refund(db, db.get(Order, order_id), reason="чарджбек")

    after = _access_until(inviter_id)
    assert (with_bonus - after).days == 5, "подаренные за оплату дни должны вернуться назад"


def test_join_bonus_has_daily_cap(client, auth):
    from app.config import settings

    limit = settings().referral_join_daily_limit
    assert limit > 0

    inviter_id = _make_user(client, auth, "ref_farm", 900_000_090)
    before = _access_until(inviter_id)

    for i in range(limit + 3):
        client.post(
            "/api/admin/referrals/invite",
            json={"inviter_telegram_id": 900_000_090, "invited_telegram_id": 900_100_000 + i},
            headers=auth,
        )

    after = _access_until(inviter_id)
    assert (after - before).days == limit * 2, "сверх потолка дни не начисляются"


def test_existing_customer_invite_is_voided(client, auth):
    inviter_tg = 900_000_100
    victim_tg = 900_000_101

    inviter_id = _make_user(client, auth, "ref_void_inviter", inviter_tg)
    before = _access_until(inviter_id)

    victim_id = _make_user(client, auth, "ref_void_victim", None)
    with SessionLocal() as db:
        victim = db.get(User, victim_id)
        victim.created_at = utcnow() - dt.timedelta(days=365)
        db.add(
            Payment(user_id=victim_id, amount=199, currency="RUB", method="platega")
        )
        db.commit()

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": inviter_tg, "invited_telegram_id": victim_tg},
        headers=auth,
    )
    assert r.status_code == 201
    assert (_access_until(inviter_id) - before).days == 2, "на переходе дни выдаются авансом"

    r = client.post(
        "/api/admin/referrals/link",
        json={"telegram_id": victim_tg, "login": "ref_void_victim"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["invited"] == 0, "аннулированное приглашение уходит из статистики"
    assert _access_until(inviter_id) == before, "авансом выданные дни забраны обратно"

    with SessionLocal() as db:
        victim = db.get(User, victim_id)
        assert referrals_service.credit_purchase(db, victim) is False
    assert _access_until(inviter_id) == before

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": inviter_tg, "invited_telegram_id": victim_tg},
        headers=auth,
    )
    assert r.status_code == 400


def test_account_of_another_telegram_is_not_invited(client, auth):
    inviter_tg = 900_000_110
    fresh_tg = 900_000_111

    inviter_id = _make_user(client, auth, "ref_foreign_inviter", inviter_tg)
    before = _access_until(inviter_id)

    other_id = _make_user(client, auth, "ref_foreign_acc", 900_000_112)

    r = client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": inviter_tg, "invited_telegram_id": fresh_tg},
        headers=auth,
    )
    assert r.status_code == 201
    assert (_access_until(inviter_id) - before).days == 2

    r = client.post(
        "/api/admin/referrals/link",
        json={"telegram_id": fresh_tg, "login": "ref_foreign_acc"},
        headers=auth,
    )
    assert r.status_code == 200
    assert _access_until(inviter_id) == before, "дни за чужую учётку возвращены"


CABINET_TG = 900_000_101
CABINET_FRIEND_TG = 900_000_102


def _as_user(client, login: str) -> dict:
    r = client.post(
        "/api/v1/login",
        json={"login": login, "password": "secret-123", "platform": "web", "device_id": "w1"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_cabinet_shows_link_earned_days_and_friends(client, auth):
    _make_user(client, auth, "ref_cab_a", CABINET_TG)
    client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": CABINET_TG, "invited_telegram_id": CABINET_FRIEND_TG},
        headers=auth,
    )

    body = client.get("/api/v1/account/referrals", headers=_as_user(client, "ref_cab_a")).json()

    assert body["linked"] is True
    assert body["invite_url"] and body["invite_url"].endswith(f"?start=ref{CABINET_TG}")
    assert body["days_total"] == 2 and body["invited"] == 1
    assert body["purchased"] == 0 and body["pending"] == 0
    assert body["join_days"] == 2 and body["purchase_days"] == 5

    assert len(body["friends"]) == 1
    friend = body["friends"][0]
    assert friend["days"] == 2 and friend["paid"] is False and friend["pending"] is False
    assert friend["joined_at"]


def test_cabinet_never_names_the_invited_person(client, auth):
    _make_user(client, auth, "ref_cab_b", 900_000_111)
    _make_user(client, auth, "ref_cab_b_friend", 900_000_112)
    client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": 900_000_111, "invited_telegram_id": 900_000_112},
        headers=auth,
    )

    raw = client.get("/api/v1/account/referrals", headers=_as_user(client, "ref_cab_b")).text
    assert "ref_cab_b_friend" not in raw
    assert "900000112" not in raw.replace("_", "")


def test_cabinet_without_telegram_sends_to_the_bot(client, auth):
    _make_user(client, auth, "ref_cab_c")

    body = client.get("/api/v1/account/referrals", headers=_as_user(client, "ref_cab_c")).json()

    assert body["linked"] is False
    assert body["invite_url"] is None
    assert body["bot_url"].startswith("https://t.me/")
    assert body["friends"] == [] and body["days_total"] == 0


def test_cabinet_page_needs_a_login(client):
    assert client.get("/api/v1/account/referrals").status_code == 401


def _code_of(client, login: str) -> str:
    body = client.get("/api/v1/account/referrals", headers=_as_user(client, login)).json()
    assert body["site_url"], "ссылка на сайт положена каждому"
    return body["site_url"].rsplit("=", 1)[1]


def _sign_up(client, login: str, ref: str | None = None):
    payload = {"login": login, "password": "dovolno-dlinnyi", "platform": "web"}
    if ref is not None:
        payload["ref"] = ref
    return client.post(
        "/api/v1/register", json=payload, headers={"X-Forwarded-For": "203.0.113.90"}
    )


def test_site_link_pays_the_inviter_without_any_telegram(client, auth):
    inviter_id = _make_user(client, auth, "ref_site_a")
    before = _access_until(inviter_id)

    r = _sign_up(client, "ref_site_guest_a", _code_of(client, "ref_site_a"))
    assert r.status_code == 201, r.text

    assert (_access_until(inviter_id) - before).days == 2

    with SessionLocal() as db:
        row = db.scalar(select(Referral).where(Referral.inviter_user_id == inviter_id))
        assert row is not None
        assert row.invited_user_id, "пришедшего опознаём учёткой"
        assert row.invited_telegram_id is None, "телеграма у гостя с сайта нет"
        assert row.join_bonus_days == 2


def test_site_invited_purchase_adds_the_second_bonus(client, auth):
    inviter_id = _make_user(client, auth, "ref_site_b")
    r = _sign_up(client, "ref_site_guest_b", _code_of(client, "ref_site_b"))
    assert r.status_code == 201, r.text
    after_join = _access_until(inviter_id)

    with SessionLocal() as db:
        guest = db.scalar(select(User).where(User.login == "ref_site_guest_b"))
        assert referrals_service.credit_purchase(db, guest) is True

    assert (_access_until(inviter_id) - after_join).days == 5

    with SessionLocal() as db:
        guest = db.scalar(select(User).where(User.login == "ref_site_guest_b"))
        assert referrals_service.credit_purchase(db, guest) is False


def test_broken_code_does_not_break_the_signup(client, auth):
    r = _sign_up(client, "ref_site_guest_c", "ЭТОГО-КОДА-НЕТ")
    assert r.status_code == 201, r.text

    with SessionLocal() as db:
        guest = db.scalar(select(User).where(User.login == "ref_site_guest_c"))
        assert db.scalar(select(Referral).where(Referral.invited_user_id == guest.id)) is None


def test_code_is_the_same_every_time(client, auth):
    _make_user(client, auth, "ref_site_d")
    assert _code_of(client, "ref_site_d") == _code_of(client, "ref_site_d")


def test_cabinet_shows_the_site_link_even_without_telegram(client, auth):
    _make_user(client, auth, "ref_site_e")
    body = client.get("/api/v1/account/referrals", headers=_as_user(client, "ref_site_e")).json()

    assert body["linked"] is False and body["invite_url"] is None
    assert "?ref=" in body["site_url"], "ссылка на сайт есть и без телеграма"


def test_site_and_bot_invites_are_counted_together(client, auth):
    _make_user(client, auth, "ref_site_f", 900_000_201)
    client.post(
        "/api/admin/referrals/invite",
        json={"inviter_telegram_id": 900_000_201, "invited_telegram_id": 900_000_202},
        headers=auth,
    )
    _sign_up(client, "ref_site_guest_f", _code_of(client, "ref_site_f"))

    body = client.get("/api/v1/account/referrals", headers=_as_user(client, "ref_site_f")).json()
    assert body["invited"] == 2, "и переход в боте, и регистрация на сайте"
    assert body["days_total"] == 4

    stats = client.get("/api/admin/referrals/stats/900000201", headers=auth).json()
    assert stats["invited"] == 2 and stats["days"] == 4
