"""
Подбор порта эндпоинта.

Обещание одно, и оно дорогое: человеку, у которого туннель НИ РАЗУ не встал,
панель предлагает другой порт; человеку, у которого он встал, порт не меняют
никогда. Нарушение в любую сторону дорого стоит. Не подобрать порт — значит
оставить человека без VPN совсем (у части операторов канонический 51820
просто не проходит). Подменить порт работающему — значит сломать
работающее ради того, кому это не нужно.

Отдельно проверяем саму подмену: она правит боевой конфиг, и ошибка здесь
не выглядит ошибкой — конфиг остаётся синтаксически верным, а туннель просто
перестаёт подниматься.

Запуск: .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import datetime as dt

import pytest

from app import provisioning
from app.db import SessionLocal, init_db
from app.models import Provisioning, Server, User, UserKey, utcnow
from app.security import hash_password

TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "DNS = 1.1.1.1\nMTU = 1280\nJc = 10\nS1 = 27\nH1 = 522668942\n"
    "\n[Peer]\nPublicKey = server-key\nAllowedIPs = 0.0.0.0/0, ::/0\n"
    "Endpoint = 10.20.30.9:51820\nPersistentKeepalive = 25\n"
)


# --- подмена порта в конфиге -------------------------------------------------


def test_port_is_read_and_replaced():
    config = provisioning.render_from_template(TEMPLATE, "priv", "10.8.1.5/32")
    assert provisioning.endpoint_port(config) == 51820

    moved = provisioning.with_endpoint_port(config, 443)
    assert "Endpoint = 10.20.30.9:443" in moved
    # Всё остальное обязано остаться дословно тем же: в конфиге хватает
    # других чисел после «=» и «:» — MTU, junk-параметры, маски, ключи.
    assert [line for line in config.splitlines() if not line.startswith("Endpoint")] == [
        line for line in moved.splitlines() if not line.startswith("Endpoint")
    ]


def test_hostname_and_ipv6_endpoints_survive():
    base = provisioning.render_from_template(TEMPLATE, "priv", "10.8.1.5/32")

    named = base.replace("10.20.30.9:51820", "nl.example.com:51820")
    assert provisioning.endpoint_port(named) == 51820
    assert "Endpoint = nl.example.com:2408" in provisioning.with_endpoint_port(named, 2408)

    # У IPv6 двоеточий полно, и порт — только тот, что после последнего.
    v6 = base.replace("10.20.30.9:51820", "[2a01:4f8::1]:51820")
    assert provisioning.endpoint_port(v6) == 51820
    assert "Endpoint = [2a01:4f8::1]:443" in provisioning.with_endpoint_port(v6, 443)


def test_endpoint_without_port_gets_one():
    bare = provisioning.render_from_template(TEMPLATE, "priv", "10.8.1.5/32").replace(
        "10.20.30.9:51820", "10.20.30.9"
    )
    assert provisioning.endpoint_port(bare) is None
    assert "Endpoint = 10.20.30.9:443" in provisioning.with_endpoint_port(bare, 443)


# --- список запасных портов --------------------------------------------------


def test_alt_ports_are_parsed_leniently():
    server = Server(name="n", host="10.20.30.9", port=51820)

    server.alt_ports = "443, 2408 ; 8443"
    assert server.alt_port_list() == [443, 2408, 8443]

    # Мусор, дубли и сам основной порт в список не попадают: лишний порт —
    # это полминуты потерянного времени у каждого, кто до него доберётся.
    server.alt_ports = "443,443,51820,0,99999,ерунда,"
    assert server.alt_port_list() == [443]

    server.alt_ports = ""
    assert server.alt_port_list() == []


# --- поведение выдачи --------------------------------------------------------


@pytest.fixture()
def setup():
    """Пользователь с подпиской и ключом на узле с запасными портами."""
    init_db()
    from app.services import billing

    with SessionLocal() as db:
        server = Server(
            name="probe-node",
            country="Тест",
            country_code="XX",
            host="10.20.30.9",
            port=51820,
            alt_ports="443,2408",
            provisioning=Provisioning.SSH,
            awg_template=TEMPLATE,
            ssh_host="10.20.30.9",
            ssh_user="root",
            ssh_password="x",
            is_active=True,
        )
        user = User(
            public_id="PV-PORT-TEST",
            login="port-test",
            password_hash=hash_password("x"),
        )
        db.add_all([server, user])
        db.commit()
        billing.grant_subscription(db, user, days=30)
        key = UserKey(
            user_id=user.id,
            server_id=server.id,
            device_id="probe-device",
            address="10.8.1.77/32",
            public_key="pub",
            config=provisioning.render_from_template(TEMPLATE, "priv", "10.8.1.77/32"),
        )
        db.add(key)
        db.commit()
        yield server.id, user.id, key.id

    with SessionLocal() as db:
        for row in (db.get(UserKey, key.id), db.get(User, user.id), db.get(Server, server.id)):
            if row is not None:
                db.delete(row)
        db.commit()


def _server_out(user_id: int, server_id: int, device_id: str = "probe-device"):
    """
    Наш узел из ответа приложению.

    Строго по идентификатору: в общем прогоне базу делят все тесты сразу, и
    «первый в списке» — это чужой сервер из соседнего модуля. По отдельности
    такой тест проходит, вместе с остальными падает, и виноватым выглядит
    последний добавленный.
    """
    from app.api_client import _servers_out
    from app.models import Session as UserSession

    with SessionLocal() as db:
        user = db.get(User, user_id)
        session = UserSession(
            user_id=user.id,
            token_hash="x",
            device_id=device_id,
            platform="android",
            expires_at=utcnow() + dt.timedelta(days=1),
        )
        out = [row for row in _servers_out(db, user, session) if row.id == server_id]
        assert out, "наш сервер обязан попасть в список"
        return out[0]


def _config_for(user_id: int, server_id: int, device_id: str = "probe-device") -> str:
    return _server_out(user_id, server_id, device_id).config


def test_never_connected_key_gets_probed_ports(setup):
    """У кого рукопожатия не было — порт по кругу, и он запоминается."""
    server_id, user_id, key_id = setup

    seen = set()
    # Колесо крутится от часов, поэтому просто дёргаем выдачу несколько раз
    # с подменой момента: важно, что перебираются ВСЕ порты узла.
    import app.api_client as api_client

    real_utcnow = api_client.utcnow
    try:
        for step in range(3):
            api_client.utcnow = lambda s=step: real_utcnow() + dt.timedelta(
                seconds=s * api_client.PORT_PROBE_SECONDS
            )
            seen.add(provisioning.endpoint_port(_config_for(user_id, server_id)))
    finally:
        api_client.utcnow = real_utcnow

    assert seen == {51820, 443, 2408}, f"перебраны не все порты: {seen}"

    with SessionLocal() as db:
        assert db.get(UserKey, key_id).endpoint_port in {51820, 443, 2408}


def test_working_key_keeps_its_port(setup):
    """У кого рукопожатие было — порт не меняется. Работающее не чинят."""
    server_id, user_id, key_id = setup

    with SessionLocal() as db:
        key = db.get(UserKey, key_id)
        key.endpoint_port = 443
        key.last_handshake_at = utcnow()
        db.commit()

    import app.api_client as api_client

    real_utcnow = api_client.utcnow
    try:
        for step in range(4):
            api_client.utcnow = lambda s=step: real_utcnow() + dt.timedelta(
                seconds=s * api_client.PORT_PROBE_SECONDS
            )
            assert provisioning.endpoint_port(_config_for(user_id, server_id)) == 443
    finally:
        api_client.utcnow = real_utcnow


def test_alt_ports_reach_the_client(setup):
    """Список запасных портов уезжает приложению — иначе перебирать нечего."""
    server_id, user_id, _ = setup
    # Основной порт идёт первым: клиент строит план перебора из порта в
    # конфиге и этого списка, а конфиг у «неподключившегося» уже подменён —
    # без 51820 в списке единственный заведомо живой порт потерялся бы.
    assert _server_out(user_id, server_id).alt_ports == [51820, 443, 2408]


def test_node_without_alt_ports_is_left_alone(setup):
    """Нет запасных портов — конфиг не трогаем вовсе."""
    server_id, user_id, _ = setup
    with SessionLocal() as db:
        db.get(Server, server_id).alt_ports = ""
        db.commit()

    assert provisioning.endpoint_port(_config_for(user_id, server_id)) == 51820

    with SessionLocal() as db:
        db.get(Server, server_id).alt_ports = "443,2408"
        db.commit()
