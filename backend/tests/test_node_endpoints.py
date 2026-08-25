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


def test_new_endpoint_gets_generated_obfuscation(server_id):
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
        with pytest.raises(PanelError, match="узла"):
            endpoints_service.create_awg_endpoint(
                db, server, handle="awg4", listen_port=51820
            )


def test_interface_name_is_whitelisted():
    assert provisioning.iface_name("awg7") == "awg7"
    for bad in ("awg", "awg100", "../etc/passwd", "awg1; rm -rf /", "awg1\nEOF", ""):
        with pytest.raises(ValueError):
            provisioning.iface_name(bad)


def test_placement_keeps_user_devices_together(server_id, node):
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

        two = endpoints_service.create_awg_endpoint(db, server, handle="awg2")
        two.state = EndpointState.ACTIVE
        two.params = {**two.params, "server_public_key": "srv"}
        one.state = EndpointState.DRAINING
        db.commit()
        db.refresh(server)
        db.refresh(user)

        again = keys_service.issue_key(db, user, server, rotate=True, device_id="phone")
        assert again.endpoint_id == one.id
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


def test_key_gets_address_port_and_obfuscation_of_its_endpoint(server_id, node):
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
        assert node.placed[key.public_key] == "awg3"


def test_legacy_key_without_endpoint_still_works(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        user = _user(db, "legacy")
        key = keys_service.issue_key(db, user, server, device_id="old")
        assert key.endpoint_id is None
        assert "Jc = 10" in key.config
        assert node.placed[key.public_key] == "awg0"


def test_reconcile_never_touches_keys_without_endpoint(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        user = _user(db, "legacy-safe")
        key = keys_service.issue_key(db, user, server, device_id="old")
        assert key.endpoint_id is None
        public_key = key.public_key

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
    node.placed["stranger-key"] = "awg0"
    with SessionLocal() as db:
        removed = traffic.reconcile_peers(db, db.get(Server, server_id))
    assert "stranger-key" in removed
    assert "stranger-key" not in node.placed


def test_reconcile_removes_stale_copy_on_wrong_interface(server_id, node):
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

    node.placed["copy-on-awg0"] = "awg0"

    with SessionLocal() as db:
        removed = traffic.reconcile_peers(db, db.get(Server, server_id))
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
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        user = _user(db, "legacy-nomove")
        key = keys_service.issue_key(db, user, server, device_id="phone")
        assert key.endpoint_id is None
        address, public_key = key.address, key.public_key

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
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = endpoints_service.create_awg_endpoint(db, server, handle="awg7", listen_port=51827)
        with pytest.raises(PanelError, match="не поднята на узле"):
            endpoints_service.set_state(db, ep, EndpointState.ACTIVE)


def test_alt_port_collision_is_rejected(server_id, node):
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
        with pytest.raises(PanelError, match="занят"):
            endpoints_service.create_awg_endpoint(
                db, server, handle="awg10", listen_port=51830, alt_ports="443"
            )
