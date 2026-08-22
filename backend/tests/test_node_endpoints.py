"""
Точки входа узла: распределение, изоляция интерфейсов и сверка.

Самое дорогое здесь — сверка. Ошибка в ней не выглядит ошибкой: панель
рапортует успех, а у людей молча пропадает VPN. Поэтому первым делом
проверяется, что ключ БЕЗ точки входа (строка старше фазы 2 — на боевом узле
таких два десятка) сверкой не трогается ни при каких обстоятельствах.

Второе по цене — изоляция интерфейсов: адрес из чужой подсети, порт чужого
интерфейса или конфиг с чужой обфускацией дают «подключено, трафика нет» —
отказ, который со стороны клиента неотличим от молчащего сервера.

Запуск: .venv/bin/python -m pytest tests/test_node_endpoints.py -q
"""

from __future__ import annotations

import ipaddress

import pytest

from app import obfuscation as obf
from app import provisioning
from app.db import SessionLocal, init_db
from app.models import (
    EndpointKind,
    EndpointState,
    NodeEndpoint,
    Provisioning,
    Server,
    User,
    UserKey,
    utcnow,
)
from app.services import endpoints as endpoints_service
from app.services import keys as keys_service
from app.services import placement, traffic
from app.services.billing import grant_subscription
from app.services.errors import PanelError

TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "DNS = 1.1.1.1, 1.0.0.1\nMTU = 1280\nJc = 10\nJmin = 39\nJmax = 628\n"
    "S1 = 27\nS2 = 140\nH1 = 522668942\nH2 = 1626372724\nH3 = 1116046423\nH4 = 129443659\n"
    "\n[Peer]\nPublicKey = legacy-server-key\nAllowedIPs = 0.0.0.0/0, ::/0\n"
    "Endpoint = 10.20.30.9:51820\nPersistentKeepalive = 25\n"
)


class FakeNode:
    """Узел, который помнит, где какой пир, вместо того чтобы их поднимать."""

    def __init__(self) -> None:
        self.placed: dict[str, str] = {}
        self.removed: list[tuple[str, str]] = []

    def add(self, _server, public_key, address, *, interface):
        self.placed[public_key] = interface

    def remove(self, _server, public_key, *, interface):
        self.removed.append((public_key, interface))
        if self.placed.get(public_key) == interface:
            self.placed.pop(public_key, None)

    def dumps(self, _server, interfaces):
        """`awg show dump` по каждому интерфейсу — из того, что реально стоит."""
        out = {}
        for name in interfaces:
            rows = [
                f"{pk}\t(none)\t1.2.3.4:1\t10.8.0.2/32\t0\t0\t0\t25"
                for pk, iface in self.placed.items()
                if iface == name
            ]
            out[name] = "iface\t(none)\toff\toff\t0\t0\t0\toff\n" + "\n".join(rows)
        return out


@pytest.fixture
def node(monkeypatch) -> FakeNode:
    fake = FakeNode()
    monkeypatch.setattr(provisioning, "add_peer_over_ssh", fake.add)
    monkeypatch.setattr(provisioning, "remove_peer_over_ssh", fake.remove)
    monkeypatch.setattr(provisioning, "dumps_over_ssh", fake.dumps)
    return fake


@pytest.fixture
def server_id() -> int:
    init_db()
    with SessionLocal() as db:
        server = Server(
            name="ep-node", country="Тест", host="10.20.30.9", port=51820,
            alt_ports="443,2408", provisioning=Provisioning.SSH, awg_template=TEMPLATE,
            ssh_host="127.0.0.1", ssh_user="root", ssh_key="dummy",
        )
        db.add(server)
        db.commit()
        return server.id


def _user(db, login: str) -> User:
    from app.security import hash_password

    user = User(login=login, name=login, password_hash=hash_password("x"))
    db.add(user)
    db.commit()
    grant_subscription(db, user, days=30)
    db.refresh(user)
    return user


# --- заведение точек входа ---------------------------------------------------


def test_new_endpoint_gets_generated_obfuscation(server_id):
    """Набор генерируется, а не копируется у соседа: в этом весь смысл фазы."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        one = endpoints_service.create_awg_endpoint(db, server, handle="awg1")
        db.refresh(server)
        two = endpoints_service.create_awg_endpoint(db, server, handle="awg2")

        assert one.obfuscation() != two.obfuscation()
        for endpoint in (one, two):
            s = endpoint.obfuscation()
            assert 3 <= s.jc <= 6
            assert len({s.h1, s.h2, s.h3, s.h4}) == 4
            assert s.s1 + 148 != s.s2 + 92
        # Порты и подсети не пересекаются.
        assert one.listen_port != two.listen_port
        assert not ipaddress.ip_network(one.subnet).overlaps(
            ipaddress.ip_network(two.subnet)
        )


def test_endpoint_rejects_port_and_subnet_collisions(server_id):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        first = endpoints_service.create_awg_endpoint(db, server, handle="awg1")
        db.refresh(server)
        with pytest.raises(PanelError, match="порт"):
            endpoints_service.create_awg_endpoint(
                db, server, handle="awg2", listen_port=first.listen_port
            )
        db.refresh(server)
        with pytest.raises(PanelError, match="подсет"):
            endpoints_service.create_awg_endpoint(
                db, server, handle="awg3", listen_port=51999, subnet=first.subnet
            )
        db.refresh(server)
        # Порт самого узла тоже занят.
        with pytest.raises(PanelError, match="узла"):
            endpoints_service.create_awg_endpoint(
                db, server, handle="awg4", listen_port=51820
            )


def test_interface_name_is_whitelisted():
    """Имя уходит в root-shell — всё, кроме awgN, обязано отбиваться."""
    assert provisioning.iface_name("awg7") == "awg7"
    for bad in ("awg", "awg100", "../etc/passwd", "awg1; rm -rf /", "awg1\nEOF", ""):
        with pytest.raises(ValueError):
            provisioning.iface_name(bad)


# --- распределение -----------------------------------------------------------


def test_placement_keeps_user_devices_together(server_id, node):
    """Устройства одного человека — на одной точке входа: один набор, один порт."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        endpoints_service.create_awg_endpoint(db, server, handle="awg1")
        db.refresh(server)
        endpoints_service.create_awg_endpoint(db, server, handle="awg2")
        db.refresh(server)
        for ep in server.endpoints:
            ep.state = EndpointState.ACTIVE
            ep.params = {**ep.params, "server_public_key": "srv"}
        db.commit()

        user = _user(db, "together")
        first = keys_service.issue_key(db, user, server, device_id="phone")
        db.refresh(user)
        second = keys_service.issue_key(db, user, server, device_id="laptop")
        assert first.endpoint_id == second.endpoint_id


def test_placement_never_moves_existing_key(server_id, node):
    """
    Точка входа выданной строки не меняется никогда — даже когда её закрыли.

    Переселение — это новая пара ключей и новый адрес, то есть разрыв туннеля.
    Оно обязано быть отдельной операцией, а не побочным эффектом продления.
    """
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        one = endpoints_service.create_awg_endpoint(db, server, handle="awg1")
        one.state = EndpointState.ACTIVE
        one.params = {**one.params, "server_public_key": "srv"}
        db.commit()
        db.refresh(server)

        user = _user(db, "stay")
        key = keys_service.issue_key(db, user, server, device_id="phone")
        assert key.endpoint_id == one.id

        # Заводим вторую и закрываем первую для новых.
        two = endpoints_service.create_awg_endpoint(db, server, handle="awg2")
        two.state = EndpointState.ACTIVE
        two.params = {**two.params, "server_public_key": "srv"}
        one.state = EndpointState.DRAINING
        db.commit()
        db.refresh(server)
        db.refresh(user)

        # Перевыпуск остаётся на своей точке входа.
        again = keys_service.issue_key(db, user, server, rotate=True, device_id="phone")
        assert again.endpoint_id == one.id
        # А новое устройство едет на открытую.
        db.refresh(user)
        fresh = keys_service.issue_key(db, user, server, device_id="tablet")
        assert fresh.endpoint_id == two.id


def test_placement_respects_capacity(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        small = endpoints_service.create_awg_endpoint(db, server, handle="awg1", capacity=1)
        small.state = EndpointState.ACTIVE
        small.params = {**small.params, "server_public_key": "srv"}
        db.commit()
        db.refresh(server)

        first = _user(db, "cap-one")
        keys_service.issue_key(db, first, server, device_id="d1")
        db.refresh(server)

        second = _user(db, "cap-two")
        with pytest.raises(PanelError, match="кончились места"):
            keys_service.issue_key(db, second, server, device_id="d2")


# --- изоляция интерфейсов ----------------------------------------------------


def test_key_gets_address_port_and_obfuscation_of_its_endpoint(server_id, node):
    """
    Адрес, порт и набор — все три из ТОЙ точки входа, куда поселили.

    Разъехаться им нельзя: адрес из чужой подсети не маршрутизируется, чужой
    порт ведёт на другой интерфейс, чужая обфускация не даёт рукопожатия. И
    ни один из трёх отказов не виден со стороны клиента.
    """
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = endpoints_service.create_awg_endpoint(
            db, server, handle="awg3", listen_port=51823, subnet="10.8.4.0/24",
            alt_ports="1443",
        )
        ep.state = EndpointState.ACTIVE
        ep.params = {**ep.params, "server_public_key": "srv-awg3"}
        db.commit()
        db.refresh(server)

        user = _user(db, "isolated")
        key = keys_service.issue_key(db, user, server, device_id="phone")

        assert ipaddress.ip_address(key.address.split("/")[0]) in ipaddress.ip_network("10.8.4.0/24")
        assert "Endpoint = 10.20.30.9:51823" in key.config
        assert "PublicKey = srv-awg3" in key.config
        expected = ep.obfuscation()
        assert f"Jc = {expected.jc}" in key.config
        assert f"H1 = {expected.h1}" in key.config
        # Пир заведён именно на этом интерфейсе.
        assert node.placed[key.public_key] == "awg3"


def test_legacy_key_without_endpoint_still_works(server_id, node):
    """Узел без точек входа обслуживается по-старому — через шаблон сервера."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        user = _user(db, "legacy")
        key = keys_service.issue_key(db, user, server, device_id="old")
        assert key.endpoint_id is None
        assert "Jc = 10" in key.config  # исторический набор из шаблона
        assert node.placed[key.public_key] == "awg0"


# --- сверка: самое опасное место ---------------------------------------------


def test_reconcile_never_touches_keys_without_endpoint(server_id, node):
    """
    Ключ без точки входа сверка не снимает НИКОГДА.

    Это те самые строки, что живут на боевом узле с самого начала. Стоит
    счесть их чужими — и один проход фонового обхода отключает всех
    действующих клиентов разом.
    """
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        user = _user(db, "legacy-safe")
        key = keys_service.issue_key(db, user, server, device_id="old")
        assert key.endpoint_id is None
        public_key = key.public_key

    # Заводим точку входа ПОСЛЕ выдачи — как это будет на бою.
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = endpoints_service.create_awg_endpoint(db, server, handle="awg1")
        ep.state = EndpointState.ACTIVE
        db.commit()

    with SessionLocal() as db:
        removed = traffic.reconcile_peers(db, db.get(Server, server_id))
    assert public_key not in removed
    assert node.placed.get(public_key) == "awg0", "пир обязан остаться на узле"


def test_reconcile_removes_unknown_peer(server_id, node):
    """Пир, которому в базе не соответствует ключ, — снимается."""
    node.placed["stranger-key"] = "awg0"
    with SessionLocal() as db:
        removed = traffic.reconcile_peers(db, db.get(Server, server_id))
    assert "stranger-key" in removed
    assert "stranger-key" not in node.placed


def test_reconcile_removes_stale_copy_on_wrong_interface(server_id, node):
    """
    Залипшая копия пира на чужом интерфейсе снимается — и именно оттуда.

    Так выглядит неудавшийся переезд: на новой точке входа пир уже есть, на
    старой остался. `awg set <не тот интерфейс> peer X remove` вернул бы 0 и
    ничего не сделал, поэтому интерфейс в команде обязан быть тем, где пир
    реально лежит.
    """
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = endpoints_service.create_awg_endpoint(db, server, handle="awg1")
        ep.state = EndpointState.ACTIVE
        ep.params = {**ep.params, "server_public_key": "srv"}
        db.commit()
        db.refresh(server)
        user = _user(db, "stale")
        key = keys_service.issue_key(db, user, server, device_id="phone")
        public_key = key.public_key
        assert node.placed[public_key] == "awg1"

    # Руками оставляем копию на awg0 — так и выглядит недоехавший переезд.
    node.placed["copy-on-awg0"] = "awg0"

    with SessionLocal() as db:
        removed = traffic.reconcile_peers(db, db.get(Server, server_id))
    # Настоящий пир на своём месте остался, посторонняя копия снята.
    assert public_key not in removed
    assert node.placed.get(public_key) == "awg1"
    assert "copy-on-awg0" in removed


def test_revoke_removes_peer_from_its_own_interface(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = endpoints_service.create_awg_endpoint(db, server, handle="awg1")
        ep.state = EndpointState.ACTIVE
        ep.params = {**ep.params, "server_public_key": "srv"}
        db.commit()
        db.refresh(server)
        user = _user(db, "revoke-iface")
        key = keys_service.issue_key(db, user, server, device_id="phone")
        public_key = key.public_key
        keys_service.revoke_key(db, key)

    assert (public_key, "awg1") in node.removed, "снимать надо с того интерфейса, где пир есть"


# --- вывод точки входа из обращения ------------------------------------------


def test_retire_refuses_while_peers_live(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = endpoints_service.create_awg_endpoint(db, server, handle="awg1")
        ep.state = EndpointState.ACTIVE
        ep.params = {**ep.params, "server_public_key": "srv"}
        db.commit()
        db.refresh(server)
        user = _user(db, "retire")
        keys_service.issue_key(db, user, server, device_id="phone")

        with pytest.raises(PanelError, match="доступов"):
            endpoints_service.set_state(db, ep, EndpointState.RETIRED)


def test_legacy_key_never_moves_to_new_endpoint(server_id, node):
    """
    Регрессия критической находки: ключ БЕЗ точки входа не переезжает.

    Его пир стоит на историческом интерфейсе, а адрес взят из ЕГО подсети.
    Отдать такому ключу новую точку входа значит завести пира с чужим адресом
    на чужом интерфейсе: туннель поднимется, трафик не пойдёт, и со стороны
    клиента это неотличимо от молчащего сервера.
    """
    # Ключ выдан ДО появления точек входа — как все 26 на боевом узле.
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        user = _user(db, "legacy-nomove")
        key = keys_service.issue_key(db, user, server, device_id="phone")
        assert key.endpoint_id is None
        address, public_key = key.address, key.public_key

    # Появились точки входа: awg0 (историческая) и новая awg5.
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        legacy = endpoints_service.create_awg_endpoint(
            db, server, handle="awg0", listen_port=51820, subnet="10.8.1.0/24"
        )
        legacy.state = EndpointState.ACTIVE
        legacy.params = {**legacy.params, "server_public_key": "srv"}
        db.commit()
        db.refresh(server)
        fresh = endpoints_service.create_awg_endpoint(
            db, server, handle="awg5", listen_port=51825, subnet="10.8.6.0/24"
        )
        fresh.state = EndpointState.ACTIVE
        fresh.params = {**fresh.params, "server_public_key": "srv5"}
        db.commit()

    # Возврат доступа: пир обязан вернуться на СВОЙ интерфейс со своим адресом.
    node.placed.clear()
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        from app.models import User as U

        user = db.scalar(__import__("sqlalchemy").select(U).where(U.login == "legacy-nomove"))
        again = keys_service.issue_key(db, user, server, device_id="phone")
        assert again.address == address, "адрес не должен меняться"
        assert again.public_key == public_key, "пара ключей не должна меняться"

    assert node.placed.get(public_key) == "awg0", "пир обязан остаться на историческом интерфейсе"


def test_endpoint_cannot_be_activated_before_applied(server_id, node):
    """Открыть для подключений можно только то, что реально стоит на узле."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = endpoints_service.create_awg_endpoint(db, server, handle="awg7", listen_port=51827)
        with pytest.raises(PanelError, match="не поднята на узле"):
            endpoints_service.set_state(db, ep, EndpointState.ACTIVE)


def test_alt_port_collision_is_rejected(server_id, node):
    """Один порт не может вести в два интерфейса — второе правило не сработает."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        first = endpoints_service.create_awg_endpoint(
            db, server, handle="awg8", listen_port=51828, alt_ports="1500,1501"
        )
        db.refresh(server)
        with pytest.raises(PanelError, match="занят"):
            endpoints_service.create_awg_endpoint(
                db, server, handle="awg9", listen_port=51829, alt_ports="1501"
            )
        db.refresh(server)
        # И с портами самого узла тоже.
        with pytest.raises(PanelError, match="занят"):
            endpoints_service.create_awg_endpoint(
                db, server, handle="awg10", listen_port=51830, alt_ports="443"
            )
