from __future__ import annotations

import datetime as dt
import itertools

import pytest
from sqlalchemy import select

from app import provisioning
from app.db import SessionLocal, init_db
from app.models import Provisioning, Server, Session, User, UserKey, utcnow
from app.security import hash_password
from app.services import devices as devices_service
from app.services import keys as keys_service

TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "[Peer]\nPublicKey = x\nEndpoint = 10.30.30.9:51820\n"
)


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


@pytest.fixture(scope="module")
def server_id() -> int:
    init_db()
    with SessionLocal() as db:
        server = Server(
            name="dev-node",
            country="Тест",
            country_code="XX",
            host="10.30.30.9",
            provisioning=Provisioning.SSH,
            awg_template=TEMPLATE,
            ssh_host="10.30.30.9",
            ssh_user="root",
            ssh_password="x",
            is_active=True,
        )
        db.add(server)
        db.commit()
        return server.id


def _user(login: str) -> int:
    with SessionLocal() as db:
        user = User(login=login, password_hash=hash_password("x"))
        db.add(user)
        db.commit()
        return user.id


_tokens = itertools.count(1)


def _session(user_id: int, device_id: str, platform: str = "windows") -> int:
    with SessionLocal() as db:
        session = Session(
            user_id=user_id,
            token_hash=f"hash-{next(_tokens)}",
            platform=platform,
            device_id=device_id,
            expires_at=utcnow() + dt.timedelta(days=30),
        )
        db.add(session)
        db.commit()
        return session.id


def test_each_device_gets_its_own_peer(server_id, node):
    user_id = _user("dev-two")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        laptop = keys_service.issue_key(db, user, server, device_id="laptop")
        phone = keys_service.issue_key(db, user, server, device_id="phone")

    assert laptop.public_key != phone.public_key
    assert laptop.address != phone.address
    assert node.peers == {laptop.public_key, phone.public_key}


def test_disconnect_removes_only_that_device(server_id, node):
    user_id = _user("dev-disconnect")
    laptop_session = _session(user_id, "laptop")
    _session(user_id, "phone")

    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        laptop = keys_service.issue_key(db, user, server, device_id="laptop")
        phone = keys_service.issue_key(db, user, server, device_id="phone")

    with SessionLocal() as db:
        target = db.get(Session, laptop_session)
        assert devices_service.disconnect(db, target) == []

    assert node.peers == {phone.public_key}, "сняли не тот пир или снесли оба"

    with SessionLocal() as db:
        rows = {
            key.device_id: key.revoked_at
            for key in db.scalars(select(UserKey).where(UserKey.user_id == user_id))
        }
        assert rows["laptop"] is not None, "ключ отключённого устройства остался живым"
        assert rows["phone"] is None, "соседнее устройство отключилось заодно"
        assert db.get(Session, laptop_session).revoked_at is not None
    assert laptop.public_key not in node.peers


def test_disconnect_keeps_shared_key_while_someone_uses_it(server_id, node):
    user_id = _user("dev-legacy")
    first = _session(user_id, "")
    second = _session(user_id, "")

    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        shared = keys_service.issue_key(db, user, server)

    with SessionLocal() as db:
        devices_service.disconnect(db, db.get(Session, first))
    assert shared.public_key in node.peers, "общий пир сняли из-под второго входа"

    with SessionLocal() as db:
        devices_service.disconnect(db, db.get(Session, second))
    assert shared.public_key not in node.peers, "последний вход ушёл, а пир остался"


def test_device_without_its_own_peer_falls_back_to_the_account_key(server_id, node):
    from app.api_client import _servers_out
    from app.services import billing

    user_id = _user("dev-fallback")
    session_id = _session(user_id, "laptop")

    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        billing.grant_subscription(db, user, days=30)
        shared = keys_service.issue_key(db, user, server)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        out = _servers_out(db, user, db.get(Session, session_id))
        mine = [s for s in out if s.id == server_id]
        assert [s.config for s in mine] == [shared.config], "устройство осталось без конфига"


def test_parallel_traffic_sync_does_not_double_count(server_id, node, monkeypatch):
    import threading

    from app.models import GB
    from app.services import billing, traffic

    user_id = _user("dev-traffic-race")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        billing.grant_subscription(db, user, days=30)
        key = keys_service.issue_key(db, user, server, device_id="counter")
        public_key = key.public_key

    dump = (
        "iface_pubkey\t(none)\toff\toff\t0\t0\t0\toff\n"
        f"{public_key}\t(none)\t10.30.30.9:51820\t10.8.0.2/32\t0\t{GB}\t0\t25\n"
    )
    monkeypatch.setattr(traffic.provisioning, "run_over_ssh", lambda *_a, **_k: dump)

    barrier = threading.Barrier(2)

    def run_sync():
        barrier.wait()
        with SessionLocal() as db:
            traffic.sync_server_traffic(db, db.get(Server, server_id))

    threads = [threading.Thread(target=run_sync) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with SessionLocal() as db:
        used = db.get(User, user_id).traffic_used_bytes
    assert used == GB, f"расход задвоился: {used} вместо {GB}"


def test_login_returns_the_peer_provisioned_during_that_same_login(server_id, node):
    from app.api_client import _provision_for_login, _servers_out
    from app.services import billing

    user_id = _user("dev-fresh-login")
    session_id = _session(user_id, "brand-new")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        billing.grant_subscription(db, user, days=30)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(Session, session_id)
        _provision_for_login(db, user, session)
        out = _servers_out(db, user, session)
        mine = [s for s in out if s.id == server_id]
        assert mine, "вход завёл пира, но список серверов на входе оказался пустым"
        assert mine[0].config, "сервер в списке есть, а конфига нет"


def test_unreachable_node_still_kills_the_token_and_revokes_the_key(server_id, node, monkeypatch):
    user_id = _user("dev-offline")
    session_id = _session(user_id, "laptop")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        keys_service.issue_key(db, user, server, device_id="laptop")

    def refuse(*_args, **_kwargs):
        raise RuntimeError("узел не ответил")

    monkeypatch.setattr(provisioning, "remove_peer_over_ssh", refuse)

    with SessionLocal() as db:
        problems = devices_service.disconnect(db, db.get(Session, session_id))
        assert problems and "dev-node" in problems[0]
        assert db.get(Session, session_id).revoked_at is not None

    with SessionLocal() as db:
        key = db.scalar(
            select(UserKey).where(UserKey.user_id == user_id, UserKey.device_id == "laptop")
        )
        assert key.revoked_at is not None, "ключ остался живым — reconcile не снимет пира, доступ вечен"


def test_background_provision_does_not_resurrect_an_unlinked_device(server_id, node):
    from app.api_client import _provision_missing_keys
    from app.services import billing

    user_id = _user("dev-resurrect")
    session_id = _session(user_id, "ghost")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        billing.grant_subscription(db, user, days=30)
        keys_service.issue_key(db, user, server, device_id="ghost")

    with SessionLocal() as db:
        devices_service.disconnect(db, db.get(Session, session_id))
    assert node.peers == set(), "после отвязки пира на узле быть не должно"

    _provision_missing_keys(user_id, "ghost")

    assert node.peers == set(), "фоновая доза воскресила пира отвязанного устройства"
    with SessionLocal() as db:
        live = db.scalars(
            select(UserKey).where(
                UserKey.user_id == user_id,
                UserKey.device_id == "ghost",
                UserKey.revoked_at.is_(None),
            )
        ).all()
        assert live == [], "у отвязанного устройства снова появился живой ключ"
