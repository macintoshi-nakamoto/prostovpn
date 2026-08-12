"""
Выдача адресов в туннеле и проверка узла.

Два обещания, каждое из которых стоило работающего доступа:

* один адрес в подсети принадлежит ровно одному ключу — второй пир с тем же
  адресом молча отбирает его на узле, и у первого туннель поднимается, а
  трафик не идёт;
* закрытый UDP-порт диагностика обязана называть закрытым, иначе полностью
  нерабочий узел показывается зелёным.

Запуск: .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import socket

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import provisioning
from app.db import SessionLocal, init_db
from app.models import Provisioning, Server, User, UserKey
from app.security import hash_password
from app.services import keys as keys_service
from app.services import diagnostics

TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "[Peer]\nPublicKey = x\nEndpoint = 10.20.30.7:51820\n"
)


@pytest.fixture(scope="module")
def server_id() -> int:
    init_db()
    with SessionLocal() as db:
        server = Server(
            name="addr-node",
            country="Тест",
            country_code="XX",
            host="10.20.30.7",
            provisioning=Provisioning.SSH,
            awg_template=TEMPLATE,
            ssh_host="10.20.30.7",
            ssh_user="root",
            ssh_password="x",
            is_active=False,  # в список приложению не попадёт
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


def test_address_is_unique_per_server(server_id):
    """Два ключа с одним адресом на одном узле база принять не должна."""
    first, second = _user("addr-uniq-1"), _user("addr-uniq-2")
    with SessionLocal() as db:
        db.add(UserKey(user_id=first, server_id=server_id, config="", address="10.8.1.200/32"))
        db.commit()
        db.add(UserKey(user_id=second, server_id=server_id, config="", address="10.8.1.200/32"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_address_is_reserved_before_ssh(server_id, monkeypatch):
    """
    Адрес занимается в базе до захода на узел, а не после.

    Раньше между выбором свободного адреса и записью строки шёл целый сеанс
    SSH, и параллельная выдача успевала взять тот же адрес. Проверяем оба
    следствия правки: упавший SSH оставляет заготовку (отозванную, чтобы
    ensure_keys повторил попытку, но с занятым адресом), и следующая выдача
    этот адрес уже не предлагает.
    """
    broken = _user("addr-reserve-1")
    good = _user("addr-reserve-2")

    def fail(*_args, **_kwargs):
        raise RuntimeError("узел не ответил")

    monkeypatch.setattr(provisioning, "add_peer_over_ssh", fail)

    with SessionLocal() as db:
        user = db.get(User, broken)
        server = db.get(Server, server_id)
        with pytest.raises(RuntimeError):
            keys_service.issue_key(db, user, server)

    with SessionLocal() as db:
        stub = db.scalar(
            select(UserKey).where(UserKey.user_id == broken, UserKey.server_id == server_id)
        )
        assert stub is not None, "адрес не занят до SSH — гонка осталась"
        assert stub.address, "заготовка без адреса ничего не резервирует"
        assert stub.revoked_at is not None, "заготовка без конфига не должна считаться живым ключом"
        assert stub.config == ""
        reserved = stub.address

    monkeypatch.setattr(provisioning, "add_peer_over_ssh", lambda *_a, **_k: None)

    with SessionLocal() as db:
        user = db.get(User, good)
        server = db.get(Server, server_id)
        key = keys_service.issue_key(db, user, server)
        assert key.address != reserved, "занятый заготовкой адрес выдан второму человеку"
        assert key.revoked_at is None and key.config


class _FakeSocket:
    """Сокет, который ведёт себя как заданный сценарий."""

    def __init__(self, on_connect=None, on_recv=None):
        self._on_connect = on_connect
        self._on_recv = on_recv

    def settimeout(self, _value):
        pass

    def connect(self, _address):
        if self._on_connect is not None:
            raise self._on_connect

    def send(self, _payload):
        return len(_payload)

    def recv(self, _size):
        raise self._on_recv or socket.timeout()

    def close(self):
        pass


def test_closed_udp_port_is_reported_closed(monkeypatch):
    """
    ICMP «порт недоступен» обязан давать «закрыт».

    До connect() эта ветка на Linux не срабатывала вовсе: ядро отбрасывает
    ICMP для несоединённого сокета, проверка уходила в таймаут и любой
    выключенный AmneziaWG показывался открытым портом.
    """
    monkeypatch.setattr(
        socket, "socket", lambda *_a, **_k: _FakeSocket(on_connect=ConnectionRefusedError())
    )
    ok, note = diagnostics._probe_udp("127.0.0.1", 51820)
    assert ok is False
    assert "закрыт" in note


def test_silent_udp_port_stays_ok(monkeypatch):
    """Молчание — норма для AmneziaWG: проверку это не валит."""
    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: _FakeSocket())
    ok, _note = diagnostics._probe_udp("127.0.0.1", 51820)
    assert ok is True
