"""
Фоновая выдача ключей при лежащем узле: не чаще раза в 90 с на устройство,
пауза по узлу после отказа SSH, и узел с отметкой down_since не трогаем.

Без этого каждый GET /servers и /s/{token} оставлял за собой SSH на 6–18 с в
общем пуле потоков, и один мёртвый узел «вешал» панель для всех.
"""

from __future__ import annotations

import time

import pytest
from fastapi import BackgroundTasks

from app import api_client, provisioning
from app.db import SessionLocal, init_db
from app.models import Provisioning, Server, User, UserKey, utcnow
from app.security import hash_password
from app.services import billing, compat
from app.services import keys as keys_service
from app.services import placement
from app import services

TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "[Peer]\nPublicKey = x\nEndpoint = 10.31.31.9:51820\n"
)


@pytest.fixture(scope="module")
def server_id() -> int:
    init_db()
    with SessionLocal() as db:
        server = Server(
            name="backoff-node",
            country="Тест",
            country_code="XX",
            host="10.31.31.9",
            provisioning=Provisioning.SSH,
            awg_template=TEMPLATE,
            ssh_host="10.31.31.9",
            ssh_user="root",
            ssh_password="x",
            is_active=True,
        )
        db.add(server)
        db.commit()
        return server.id


@pytest.fixture()
def only_this_server(server_id, monkeypatch):
    # В общей тестовой базе живут узлы других модулей — здесь считаем
    # попытки только к своему.
    def mine(db):
        return [db.get(Server, server_id)]

    monkeypatch.setattr(keys_service, "active_servers", mine)
    monkeypatch.setattr(services, "active_servers", mine)


@pytest.fixture()
def dead_node(monkeypatch):
    calls = {"n": 0}

    def add(*_args, **_kwargs):
        calls["n"] += 1
        raise RuntimeError("SSH: connection timed out")

    monkeypatch.setattr(provisioning, "add_peer_over_ssh", add)
    monkeypatch.setattr(provisioning, "remove_peer_over_ssh", lambda *a, **k: None)
    return calls


def _user(login: str) -> int:
    with SessionLocal() as db:
        user = User(login=login, password_hash=hash_password("x"))
        db.add(user)
        db.commit()
        billing.grant_subscription(db, user, days=30, plan="basic")
        return user.id


def _shift_clock(monkeypatch, seconds: float) -> None:
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + seconds)


def test_background_task_once_per_device(server_id, only_this_server, monkeypatch):
    user_id = _user("backoff-once")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        background = BackgroundTasks()
        api_client._serve_targets(db, user, "phone", background)
        api_client._serve_targets(db, user, "phone", background)
        assert len(background.tasks) == 1, "второй запрос подряд снова поставил выдачу"

        _shift_clock(monkeypatch, api_client.PROVISION_RETRY_SECONDS + 1)
        api_client._serve_targets(db, user, "phone", background)
        assert len(background.tasks) == 2


def test_dead_node_probed_once_then_quiet(server_id, only_this_server, dead_node, monkeypatch):
    user_id = _user("backoff-dead")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        warnings = keys_service.ensure_keys(db, user, devices={"a", "b", "c"})
        assert dead_node["n"] == 1, "три устройства — три SSH к мёртвому узлу"
        assert warnings and "timed out" in warnings[0]

        warnings = keys_service.ensure_keys(db, user, devices={"a", "b", "c"})
        assert dead_node["n"] == 1, "пауза не выдержана"
        assert any("позже" in w for w in warnings)

        _shift_clock(monkeypatch, keys_service.NODE_QUIET_BASE + 1)
        keys_service.ensure_keys(db, user, devices={"a", "b", "c"})
        assert dead_node["n"] == 2
        count, until = keys_service._node_failures[server_id]
        assert count == 2
        assert until - time.monotonic() == pytest.approx(2 * keys_service.NODE_QUIET_BASE, abs=1)


def test_down_since_skips_node(server_id, only_this_server, monkeypatch):
    calls = {"n": 0}

    def add(*_args, **_kwargs):
        calls["n"] += 1

    monkeypatch.setattr(provisioning, "add_peer_over_ssh", add)
    user_id = _user("backoff-down")
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        server.down_since = utcnow()
        db.commit()
        user = db.get(User, user_id)
        warnings = keys_service.ensure_keys(db, user, devices={""})
        assert calls["n"] == 0
        assert warnings and "backoff-node" in warnings[0]

        server.down_since = None
        db.commit()
        assert keys_service.ensure_keys(db, user, devices={""}) == []
        assert calls["n"] == 1


def test_migrate_skips_quiet_node(server_id, only_this_server, monkeypatch):
    user_id = _user("backoff-migrate")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        server = db.get(Server, server_id)
        key = UserKey(user_id=user.id, server_id=server.id, device_id="", config="[Interface]", public_key="k", address="10.8.9.2/32")
        db.add(key)
        db.commit()

        issued = {"n": 0}

        def fake_issue(db_, user_, server_, rotate=False, device_id=""):
            issued["n"] += 1
            return key

        monkeypatch.setattr(keys_service, "issue_key", fake_issue)
        monkeypatch.setattr(placement, "pick_endpoint", lambda *a, **k: object())
        monkeypatch.setattr(placement, "awg_level_of", lambda ep: 2)
        token = compat.CLIENT_AWG_LEVEL.set(2)
        try:
            keys_service._note_node_failure(server)
            assert keys_service.migrate_awg(db, user, server, key) is key
            assert issued["n"] == 0, "к лежащему узлу пошли по SSH прямо из запроса"

            keys_service._note_node_ok(server)
            assert keys_service.migrate_awg(db, user, server, key) is key
            assert issued["n"] == 1
        finally:
            compat.CLIENT_AWG_LEVEL.reset(token)
