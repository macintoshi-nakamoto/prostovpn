from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app import provisioning
from app.db import SessionLocal, init_db
from app.models import (
    HANDSHAKE_WINDOW,
    Plan,
    Provisioning,
    Server,
    Subscription,
    User,
    UserKey,
    utcnow,
)
from app.public_api import _ios_device_rows, _ios_out
from app.security import hash_password
from app.services import billing, ios
from app.services import keys as keys_service


class FakeNode:
    def __init__(self) -> None:
        self.peers: set[str] = set()
        self.placed: dict[str, str] = {}
        self.removed_from: dict[str, str] = {}

    def add(self, _server, public_key, _address, *, interface="awg0") -> None:
        self.peers.add(public_key)
        self.placed[public_key] = interface

    def remove(self, _server, public_key, *, interface="awg0") -> None:
        self.peers.discard(public_key)
        self.removed_from[public_key] = interface


@pytest.fixture
def node(monkeypatch) -> FakeNode:
    fake = FakeNode()
    monkeypatch.setattr(provisioning, "add_peer_over_ssh", fake.add)
    monkeypatch.setattr(provisioning, "remove_peer_over_ssh", fake.remove)
    return fake


TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "[Peer]\nPublicKey = x\nEndpoint = 10.40.40.9:51820\n"
)


@pytest.fixture(scope="module")
def server_id() -> int:
    init_db()
    with SessionLocal() as db:
        server = Server(
            name="ios-node",
            country="Тест",
            country_code="XY",
            host="10.40.40.9",
            provisioning=Provisioning.SSH,
            awg_template=TEMPLATE,
            ssh_host="10.40.40.9",
            ssh_user="root",
            ssh_password="x",
            is_active=True,
        )
        db.add(server)
        db.commit()
        return server.id


def _paid_user(login: str, days: int = 30) -> int:
    with SessionLocal() as db:
        user = User(login=login, password_hash=hash_password("x"), ios_access=True)
        db.add(user)
        db.flush()
        db.add(
            Subscription(
                user_id=user.id,
                plan="basic",
                price=300,
                period_days=days,
                starts_at=utcnow() - dt.timedelta(days=1),
                expires_at=utcnow() + dt.timedelta(days=days),
            )
        )
        db.commit()
        return user.id


def _slot_keys(db, user_id: int, server_id: int) -> list[UserKey]:
    return list(
        db.scalars(
            select(UserKey).where(
                UserKey.user_id == user_id,
                UserKey.server_id == server_id,
                UserKey.device_id == "ios-1",
            )
        )
    )


@pytest.fixture(scope="module")
def other_server_id(server_id) -> int:
    with SessionLocal() as db:
        server = Server(
            name="ios-node-2",
            country="Тест-2",
            country_code="ZZ",
            host="10.40.40.10",
            provisioning=Provisioning.SSH,
            awg_template=TEMPLATE,
            ssh_host="10.40.40.10",
            ssh_user="root",
            ssh_password="x",
            is_active=True,
        )
        db.add(server)
        db.commit()
        return server.id


def _slot_servers(db, user_id: int, slot: str = "ios-1") -> set[int]:
    return set(
        db.scalars(
            select(UserKey.server_id).where(
                UserKey.user_id == user_id, UserKey.device_id == slot
            )
        )
    )


def _read_like_amnezia(payload: str) -> dict:
    import base64
    import json as jsonlib
    import struct
    import zlib

    raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    magic, chunks, index, length = struct.unpack(">hBBI", raw[:8])
    assert magic == 1984, "клиент узнаёт свой код по метке 1984"
    assert chunks == 1 and index == 0, "код должен быть единственным куском"
    body = raw[8:]
    assert len(body) == length, "длина QByteArray обязана сойтись с данными"
    return jsonlib.loads(zlib.decompress(body[4:]))


def test_qr_payload_is_read_back_the_way_amnezia_reads_it(server_id, node):
    user_id = _paid_user("ios-qr-1")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.add_key(db, user, server_id=server_id)
        db.refresh(user)
        key = ios.keys(user)[0]

    assert key.qr_payload, "у живого ключа код обязан быть"
    из_кода = _read_like_amnezia(key.qr_payload)
    из_ссылки = provisioning.read_vpn_key(key.vpn_url)
    assert из_кода == из_ссылки, "код и ссылка обязаны давать один конфиг"
    assert из_кода.get("containers"), "клиент ищет в конфиге приметы своего формата"


def test_qr_payload_is_absent_when_the_key_does_not_fit_one_code():
    import base64

    big = bytes((i * 37 + 11) % 256 for i in range(provisioning.QR_CHUNK_BYTES + 1))
    link = base64.urlsafe_b64encode(big).decode().rstrip("=")
    assert provisioning.build_qr_payload("vpn://" + link) is None

    впритык = bytes((i * 37 + 11) % 256 for i in range(provisioning.QR_CHUNK_BYTES))
    край = base64.urlsafe_b64encode(впритык).decode().rstrip("=")
    assert provisioning.build_qr_payload("vpn://" + край), "ровно в размер — код есть"


def test_qr_payload_survives_a_link_without_the_prefix(server_id, node):
    user_id = _paid_user("ios-qr-2")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.add_key(db, user, server_id=server_id)
        db.refresh(user)
        key = ios.keys(user)[0]

    без_префикса = key.vpn_url[len("vpn://") :]
    assert provisioning.build_qr_payload(без_префикса) == key.qr_payload


def test_key_lands_only_in_the_chosen_country(server_id, other_server_id, node):
    user_id = _paid_user("ios-pick-1")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        number, warnings = ios.add_key(db, user, server_id=other_server_id)
        assert warnings == []
        assert number == 1
        assert _slot_servers(db, user_id) == {other_server_id}


def test_renewal_does_not_spread_the_key_to_other_countries(
    server_id, other_server_id, node
):
    user_id = _paid_user("ios-pick-2")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.add_key(db, user, server_id=other_server_id)
        db.refresh(user)
        for key in list(user.keys):
            if key.device_id == "ios-1":
                keys_service.revoke_key(db, key)
        db.refresh(user)

        ios.sync(db, user)
        assert _slot_servers(db, user_id) == {other_server_id}


def test_unknown_country_is_refused(server_id, node):
    user_id = _paid_user("ios-pick-3")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        with pytest.raises(ios.PanelError):
            ios.add_key(db, user, server_id=999_999)


def test_ios_key_becomes_a_device_only_after_traffic(server_id, node):
    """Слот ключа — устройство с момента выдачи (место в лимите занято),
    а подключение видно и на строке устройства, и на самом ключе."""
    user_id = _paid_user("ios-dev-1")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.sync(db, user, home=server_id)
        db.refresh(user)
        now = utcnow()

        rows = _ios_device_rows(user, now)
        assert len(rows) == 1 and rows[0].kind == "ios_key" and rows[0].slot == 1
        assert rows[0].last_seen_at is None and rows[0].is_connected is False
        assert user.devices_used(now) == 1
        assert [k.is_connected for k in _ios_out(db, user, now).keys] == [False]

        key = _slot_keys(db, user_id, server_id)[0]
        key.last_handshake_at = now - dt.timedelta(seconds=30)
        db.commit()
        db.refresh(user)

        rows = _ios_device_rows(user, now)
        assert len(rows) == 1 and rows[0].kind == "ios_key" and rows[0].slot == 1
        assert rows[0].id == -1 and rows[0].is_connected is True
        assert rows[0].last_seen_at is not None
        assert user.devices_used(now) == 1
        assert [k.is_connected for k in _ios_out(db, user, now).keys] == [True]
        assert user.is_vpn_connected(now) is True

        key.last_handshake_at = now - HANDSHAKE_WINDOW - dt.timedelta(minutes=2)
        db.commit()
        db.refresh(user)
        rows = _ios_device_rows(user, now)
        assert len(rows) == 1 and rows[0].is_connected is False
        assert [k.is_connected for k in _ios_out(db, user, now).keys] == [False]
        assert user.is_vpn_connected(now) is False


def test_disconnect_removes_peer_and_survives_provisioning(server_id, node):
    user_id = _paid_user("ios-dev-2")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.sync(db, user, home=server_id)
        db.refresh(user)
        key = _slot_keys(db, user_id, server_id)[0]
        public_key = key.public_key
        config = key.config
        key.last_handshake_at = utcnow()
        db.commit()
        assert public_key in node.peers

        db.refresh(user)
        ios.disconnect_key(db, user, 1)
        db.refresh(user)
        assert public_key not in node.peers
        assert _ios_out(db, user, utcnow()).keys == []

        keys_service.ensure_keys(db, user)
        ios.sync(db, user, home=server_id)
        db.refresh(user)
        assert public_key not in node.peers
        assert all(k.revoked_at is not None for k in _slot_keys(db, user_id, server_id))

        ios.reconnect_key(db, user, 1)
        db.refresh(user)
        fresh = _slot_keys(db, user_id, server_id)[0]
        assert public_key in node.peers
        assert fresh.public_key == public_key and fresh.config == config
        assert fresh.revoked_at is None and fresh.disconnected_at is None

        assert [k for k in _ios_out(db, db.get(User, user_id), utcnow()).keys if k.is_connected] == []


def test_disconnected_key_is_shown_and_counts_a_slot(server_id, node):
    user_id = _paid_user("ios-dev-3")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.sync(db, user, home=server_id)
        db.refresh(user)
        ios.disconnect_key(db, user, 1)
        db.refresh(user)

        assert ios.keys(user) == []
        off = [k for k in ios.keys(user, include_disconnected=True) if k.disconnected]
        assert len(off) >= 1 and all(not k.is_active for k in off)

        assert ios.free_slot(user) == 2


def _plan(db, code: str, name: str, kopecks: int, days: int) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        plan = Plan(code=code, name=name, period_days=days)
        db.add(plan)
    plan.set_price(kopecks)
    plan.period_days = days
    db.commit()
    db.refresh(plan)
    return plan


def test_same_plan_extend_prolongs_visibly(server_id):
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)

        user = User(login="extend-1", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        first = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        first_id, first_end = first.id, first.expires_at

        again = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        db.refresh(user)
        assert again.id == first_id
        assert again.expires_at == first_end + dt.timedelta(days=30)

        assert user.upcoming_subscriptions() == []
        assert user.access_days_left() >= 59
        assert user.active_subscription().id == first_id


def test_plan_change_queues_after_paid_days(server_id):
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)
        pro = _plan(db, "q-pro", "Годовая", 149_900, 365)

        user = User(login="queue-1", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        first = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        first_end = first.expires_at

        second = billing.grant_subscription(db, user, days=365, plan=pro, price=1499)
        db.refresh(user)
        assert second.starts_at == first_end
        assert second.expires_at == first_end + dt.timedelta(days=365)

        current = user.active_subscription()
        assert current.id == first.id and current.plan == "q-basic"
        assert user.current_plan().code == "q-basic"

        queued = user.upcoming_subscriptions()
        assert [s.id for s in queued] == [second.id]
        assert user.access_expires_at() == second.expires_at
        assert user.access_days_left() >= 30 + 365 - 1

        later = first_end + dt.timedelta(hours=1)
        assert user.active_subscription(later).id == second.id
        assert user.current_plan(later).code == "q-pro"


def test_queue_stays_one_period_on_repeated_change(server_id):
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)
        pro = _plan(db, "q-pro", "Годовая", 149_900, 365)
        half = _plan(db, "q-half", "Полугодовая", 89_900, 180)

        user = User(login="queue-2", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        billing.grant_subscription(db, user, days=365, plan=pro, price=1499)
        billing.grant_subscription(db, user, days=180, plan=half, price=899)
        db.refresh(user)

        # Оплаченные периоды в очереди не сгорают при покупке другого тарифа —
        # новый встаёт в хвост (коммит «биллинг: оплаченные периоды очереди не
        # сгорают…»). Раньше очередь держала ровно один период, и вторая
        # покупка затирала первую вместе с деньгами за неё.
        upcoming = user.upcoming_subscriptions()
        assert [s.plan for s in upcoming] == ["q-pro", "q-half"]
        assert user.active_subscription().plan == "q-basic"


def test_free_trial_does_not_queue_behind_paid(server_id):
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)
        trial = _plan(db, "q-trial", "Пробный", 0, 2)

        user = User(login="trial-1", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        paid = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        got = billing.grant_subscription(db, user, days=2, plan=trial, price=0)
        db.refresh(user)
        assert got.id == paid.id
        assert user.upcoming_subscriptions() == []
        assert [s for s in user.subscriptions if not s.is_cancelled] == [paid]


def test_paid_purchase_during_trial_starts_now(server_id):
    with SessionLocal() as db:
        trial = _plan(db, "q-trial", "Пробный", 0, 2)
        year = _plan(db, "q-year", "Годовая", 149_900, 365)

        user = User(login="trial-2", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        billing.grant_subscription(db, user, days=2, plan=trial, price=0)
        billing.grant_subscription(db, user, days=365, plan=year, price=1499)
        db.refresh(user)

        act = user.active_subscription()
        assert act is not None and act.plan == "q-year"
        assert user.current_plan().code == "q-year"
        assert user.upcoming_subscriptions() == []


def test_admin_extend_visibly_adds_days_near_expiry(server_id):
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)
        user = User(login="near-expiry", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        sub = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        sub.starts_at = utcnow() - dt.timedelta(days=30)
        sub.expires_at = utcnow() + dt.timedelta(hours=3)
        db.commit()
        db.refresh(user)
        assert user.access_days_left() == 0

        billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        db.refresh(user)
        assert user.access_days_left() >= 30
        assert user.has_access() is True


def test_collapse_repairs_paid_stuck_behind_trial(server_id):
    with SessionLocal() as db:
        trial = _plan(db, "q-trial", "Пробный", 0, 2)
        year = _plan(db, "q-year", "Годовая", 149_900, 365)

        user = User(login="stuck-1", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        now = utcnow()
        db.add(
            Subscription(
                user_id=user.id, plan="q-trial", price=0, period_days=2,
                starts_at=now - dt.timedelta(days=1), expires_at=now + dt.timedelta(days=1),
            )
        )
        db.add(
            Subscription(
                user_id=user.id, plan="q-year", plan_id=year.id, price=1499, period_days=365,
                starts_at=now + dt.timedelta(days=1), expires_at=now + dt.timedelta(days=366),
            )
        )
        db.commit()
        db.refresh(user)
        assert user.active_subscription().plan == "q-trial"

        fixed = billing.collapse_corrupted_queues(db)
        db.refresh(user)
        logins = [f["login"] for f in fixed]
        assert "stuck-1" in logins
        assert user.active_subscription().plan == "q-year"
        assert user.upcoming_subscriptions() == []
        assert user.has_access() is True
        assert all(f["login"] != "stuck-1" for f in billing.collapse_corrupted_queues(db))


def test_country_list_comes_before_the_first_key(server_id, other_server_id, node):
    from fastapi.testclient import TestClient

    from app.main import app

    _paid_user("ios-offer-1")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == "ios-offer-1"))
        user.ios_access = False
        db.commit()

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/login",
            json={"login": "ios-offer-1", "password": "x", "platform": "web", "device_id": "o1"},
        )
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['token']}"}

        block = client.get("/api/v1/account", headers=headers).json()["ios"]
        assert block["available"] is False
        offered = {s["id"] for s in block["servers"]}
        assert server_id in offered and other_server_id in offered
        assert all(s["country"] for s in block["servers"]), "страну надо чем-то подписать"


def test_account_api_shows_ios_device_and_disconnect_cycle(server_id, node):
    from fastapi.testclient import TestClient

    from app.main import app

    user_id = _paid_user("ios-http-1")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.sync(db, user, home=server_id)
        db.refresh(user)
        key = _slot_keys(db, user_id, server_id)[0]
        key.last_handshake_at = utcnow()
        db.commit()

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/login",
            json={"login": "ios-http-1", "password": "x", "platform": "web", "device_id": "b1"},
        )
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['token']}"}

        account = client.get("/api/v1/account", headers=headers).json()
        # Вход с сайта — не устройство, а iPhone с рабочим ключом — да.
        rows = [d for d in account["devices"] if d["kind"] == "ios_key"]
        assert [d["kind"] for d in account["devices"]] == ["ios_key"]
        assert rows[0]["slot"] == 1 and rows[0]["id"] == -1
        assert rows[0]["is_connected"] is True
        assert account["ios"]["keys"], "рабочая ссылка должна быть в списке"
        assert account["ios"]["keys"][0]["is_connected"] is True
        link_before = account["ios"]["keys"][0]["vpn_url"]
        assert account["upcoming"] == []
        assert account["expires_total_at"] is not None

        account = client.post("/api/v1/account/ios/keys/1/disconnect", headers=headers).json()
        assert [d for d in account["devices"] if d["kind"] == "ios_key"] == []
        assert account["ios"]["keys"] == []
        off = account["ios"]["disconnected_keys"]
        assert {k["slot"] for k in off} == {1}
        assert all(k["disconnected"] for k in off)
        assert account["ios"]["keys_count"] == 1

        account = client.post("/api/v1/account/ios/keys/1/enable", headers=headers).json()
        assert account["ios"]["disconnected_keys"] == []
        assert account["ios"]["keys"][0]["vpn_url"] == link_before
        # Включённый обратно ключ снова занимает место — строкой без даты:
        # после отключения рукопожатие обнулено, подключения ещё не было.
        rows = [d for d in account["devices"] if d["kind"] == "ios_key"]
        assert len(rows) == 1 and rows[0]["slot"] == 1
        assert rows[0]["is_connected"] is False and rows[0]["last_seen_at"] is None
        assert account["devices_used"] == 1 and account["devices_left"] == account["device_limit"] - 1


def test_purchase_during_trial_starts_immediately(server_id):
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)

        user = User(login="queue-trial", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        now = utcnow()
        db.add(
            Subscription(
                user_id=user.id,
                plan="trial",
                price=0,
                period_days=2,
                starts_at=now - dt.timedelta(hours=1),
                expires_at=now + dt.timedelta(days=2),
            )
        )
        db.commit()

        paid = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        db.refresh(user)
        assert paid.starts_at <= utcnow()
        assert user.active_subscription().id == paid.id
        assert user.current_plan().code == "q-basic"
        assert user.upcoming_subscriptions() == []
