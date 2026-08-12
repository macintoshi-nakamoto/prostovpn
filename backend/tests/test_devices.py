"""
Устройства: свой пир каждому и настоящее отключение.

Два обещания, которые до этого держались только на словах:

* «Отключить устройство» снимает пира именно этого устройства с узла, а не
  гасит токен и оставляет туннель работать;
* соседние устройства того же человека при этом не отваливаются.

Оба проверяются на поддельном SSH: настоящий узел тестам не нужен, важно,
какие ключи с него просят снять и в каком порядке.
"""

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
    """Узел, который помнит свои пиры вместо того, чтобы их поднимать."""

    def __init__(self) -> None:
        self.peers: set[str] = set()

    def add(self, _server, public_key, _address) -> None:
        self.peers.add(public_key)

    def remove(self, _server, public_key) -> None:
        self.peers.discard(public_key)


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


# Токен в таблице уникален, а в тестах их заводится сколько угодно, в том
# числе несколько с одним пустым device_id, — поэтому просто счётчик.
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
    """Два устройства одного человека — два разных ключа и два адреса."""
    user_id = _user("dev-two")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        laptop = keys_service.issue_key(db, user, server, device_id="laptop")
        phone = keys_service.issue_key(db, user, server, device_id="phone")

    assert laptop.public_key != phone.public_key
    assert laptop.address != phone.address
    assert node.peers == {laptop.public_key, phone.public_key}


def test_disconnect_removes_only_that_device(server_id, node):
    """
    Отключение снимает пира одного устройства и не трогает соседей.

    Ровно то, ради чего пир вообще стал принадлежать устройству: пока он был
    общим, снять его значило отключить человека целиком.
    """
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
    """
    Общий «ключ учётки» не снимается, пока на нём сидит ещё кто-то.

    Так ходят приложения старых версий: идентификатора установки они не
    присылают, пир у них один на всех. Отключить один такой вход и уронить
    заодно остальные — хуже, чем не отключить пира вовсе: токен всё равно
    погашен, и приложение попросит войти заново.
    """
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


def test_unreachable_node_still_kills_the_token(server_id, node, monkeypatch):
    """
    Узел не ответил — сессия всё равно погашена, а причина названа.

    Оставлять живой токен из-за недоступного узла нельзя: это худший из
    исходов, доступ остаётся и в приложении, и в туннеле.
    """
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
