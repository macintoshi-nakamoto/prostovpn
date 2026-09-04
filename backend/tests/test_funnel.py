"""Воронка: этапы считаются по фактам в базе, а не по отдельному трекингу."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    Payment,
    Referral,
    Session,
    Subscription,
    SubscriptionToken,
    TrafficSample,
    User,
    UserKey,
    utcnow,
)
from app.security import hash_password, token_hash
from app.services import funnel


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


def _user(db, login: str, *, created_days_ago: float, telegram_id: int | None = None) -> User:
    user = User(
        login=login,
        password_hash=hash_password("x"),
        telegram_id=telegram_id,
        created_at=utcnow() - dt.timedelta(days=created_days_ago),
    )
    db.add(user)
    db.flush()
    return user


def _session(db, user: User, platform: str, hours_after: float = 1) -> None:
    db.add(
        Session(
            user_id=user.id,
            token_hash=token_hash(f"tok-{user.login}-{platform}"),
            platform=platform,
            created_at=user.created_at + dt.timedelta(hours=hours_after),
            last_seen_at=user.created_at + dt.timedelta(hours=hours_after),
            expires_at=utcnow() + dt.timedelta(days=30),
        )
    )


def _server_id(db) -> int:
    from app.models import Provisioning, Server

    server = Server(
        name="funnel-node",
        country="Нидерланды",
        country_code="NL",
        host="10.66.0.1",
        provisioning=Provisioning.SHARED,
        shared_config="[Interface]\nAddress = 10.0.0.2/32\n",
    )
    db.add(server)
    db.flush()
    return server.id


@pytest.fixture(scope="module")
def baseline(client):
    """Снимок воронки ДО наших людей: база тестов общая на весь прогон, и
    другие модули оставляют в ней своих пользователей."""
    with SessionLocal() as db:
        return {"all": funnel.build(db, None), "week": funnel.build(db, 7)}


def _delta(after: dict, before: dict, key: str) -> int:
    return _stage(after, key)["count"] - _stage(before, key)["count"]


def _by_source(data: dict) -> dict:
    return {s["source"]: s for s in data["sources"]}


def _src(after: dict, before: dict, source: str, field: str) -> int:
    return _by_source(after).get(source, {}).get(field, 0) - _by_source(before).get(source, {}).get(field, 0)


@pytest.fixture(scope="module")
def people(client, baseline):
    """Пять судеб: только регистрация; ключ без подключения; подключился;
    оплатил один раз (по приглашению); платит повторно (с сайта)."""
    with SessionLocal() as db:
        server_id = _server_id(db)

        idle = _user(db, "fn-idle", created_days_ago=3, telegram_id=1001)
        _session(db, idle, "telegram")

        keyed = _user(db, "fn-keyed", created_days_ago=2, telegram_id=1002)
        _session(db, keyed, "telegram")
        db.add(
            UserKey(
                user_id=keyed.id,
                server_id=server_id,
                device_id="ios-1",
                config="[Interface]\n",
                public_key="fn-key-1",
                address="10.66.0.5/32",
                created_at=keyed.created_at + dt.timedelta(hours=2),
            )
        )

        linked = _user(db, "fn-linked", created_days_ago=2, telegram_id=1003)
        _session(db, linked, "telegram")
        db.add(
            SubscriptionToken(
                user_id=linked.id,
                device_id="ext-1",
                token_hash=token_hash("fn-sub-1"),
                created_at=linked.created_at + dt.timedelta(hours=1),
            )
        )
        db.add(
            TrafficSample(
                user_id=linked.id,
                server_id=server_id,
                delta_bytes=1000,
                rx_bytes=1000,
                tx_bytes=0,
                sampled_at=linked.created_at + dt.timedelta(hours=3),
            )
        )

        payer = _user(db, "fn-payer", created_days_ago=5, telegram_id=1004)
        _session(db, payer, "telegram")
        _session(db, payer, "android", hours_after=2)
        db.add(
            TrafficSample(
                user_id=payer.id,
                server_id=server_id,
                delta_bytes=1000,
                rx_bytes=1000,
                tx_bytes=0,
                sampled_at=payer.created_at + dt.timedelta(hours=4),
            )
        )
        db.add(
            Payment(
                user_id=payer.id,
                amount=199,
                currency="RUB",
                paid_at=payer.created_at + dt.timedelta(days=2),
            )
        )
        db.add(Referral(inviter_telegram_id=1001, invited_telegram_id=1004, invited_user_id=payer.id))

        loyal = _user(db, "fn-loyal", created_days_ago=40)
        _session(db, loyal, "web")
        _session(db, loyal, "windows", hours_after=1)
        db.add(
            TrafficSample(
                user_id=loyal.id,
                server_id=server_id,
                delta_bytes=1000,
                rx_bytes=1000,
                tx_bytes=0,
                sampled_at=loyal.created_at + dt.timedelta(hours=2),
            )
        )
        for offset in (1, 31):
            db.add(
                Payment(
                    user_id=loyal.id,
                    amount=199,
                    currency="RUB",
                    paid_at=loyal.created_at + dt.timedelta(days=offset),
                )
            )
        db.commit()
        return {u.login: u.id for u in (idle, keyed, linked, payer, loyal)}


def _stage(data: dict, key: str) -> dict:
    return next(s for s in data["stages"] if s["key"] == key)


def test_stages_count_each_person_once(people, baseline):
    with SessionLocal() as db:
        data = funnel.build(db, None)
    before = baseline["all"]

    assert _delta(data, before, "registered") == 5
    # Доступ: ключ, ссылка и входы приложения (payer, loyal); idle — нет.
    assert _delta(data, before, "setup") == 4
    assert _delta(data, before, "connected") == 3
    assert _delta(data, before, "paid") == 2
    assert _delta(data, before, "repeat") == 1
    if before["users"] == 0:
        assert _stage(data, "paid")["pct_prev"] == pytest.approx(66.7, abs=0.1)
        assert _stage(data, "connected")["pct_total"] == 60.0


def test_period_cuts_by_registration_date(people, baseline):
    with SessionLocal() as db:
        recent = funnel.build(db, 7)
    before = baseline["week"]
    ours = {u["login"] for u in recent["stuck"] if u["login"].startswith("fn-")}
    assert _delta(recent, before, "registered") == 4, "loyal зарегистрирован 40 дней назад"
    assert _delta(recent, before, "repeat") == 0
    # Застряли: idle и keyed — больше суток без подключения.
    assert recent["stuck_count"] - before["stuck_count"] == 2
    assert ours == {"fn-idle", "fn-keyed"}
    keyed = next(u for u in recent["stuck"] if u["login"] == "fn-keyed")
    assert keyed["has_setup"] is True and keyed["source"] == "telegram"


def test_sources_and_cohorts(people, baseline):
    with SessionLocal() as db:
        data = funnel.build(db, None)
    before = baseline["all"]
    assert _src(data, before, "referral", "registered") == 1 and _src(data, before, "referral", "paid") == 1
    assert _src(data, before, "site", "registered") == 1 and _src(data, before, "site", "paid") == 1
    assert _src(data, before, "telegram", "registered") == 3 and _src(data, before, "telegram", "paid") == 0
    ours = sum(c["registered"] for c in data["cohorts"]) - sum(c["registered"] for c in before["cohorts"])
    assert ours == 5
    if before["users"] == 0:
        assert data["median_hours_to_connect"] == pytest.approx(3.0, abs=0.5)
        assert data["median_days_to_pay"] == pytest.approx(1.5, abs=0.1)


def test_admin_endpoint_returns_camel_case(client, auth, people):
    r = client.get("/api/admin/funnel", params={"days": 0}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["periodDays"] is None
    assert [s["key"] for s in body["stages"]] == ["registered", "setup", "connected", "paid", "repeat"]
    assert body["stuckCount"] >= 2 and all(u["publicId"] for u in body["stuck"])
    assert client.get("/api/admin/funnel", params={"days": 7}, headers=auth).json()["periodDays"] == 7


def test_empty_database_gives_zero_funnel():
    with SessionLocal() as db:
        data = funnel.build(db, 0)  # 0 → None: за всё время, но людей в тестовой базе может и не быть
    assert len(data["stages"]) == 5
    assert all(isinstance(s["count"], int) for s in data["stages"])
