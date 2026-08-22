"""
Второй протокол: VLESS + XTLS-Reality.

Три вещи, ради которых этот файл существует.

Первое — приоритет. VLESS обязан идти ПОСЛЕ awg: он медленнее и дороже по
батарее, и клиент, взявший его первым, ухудшит сервис молча. Проверяется не
константой в коде, а порядком в готовом ответе подписки.

Второе — отзыв. У awg снятие пира останавливает трафик сразу, у VLESS доступ
живёт в конфиге узла. Пропущенный путь отзыва — это оплата, которая протекает:
подписка кончилась, а человек ходит.

Третье — секреты. UUID клиента и приватный ключ Reality не должны лежать в базе
открытым текстом и не должны уезжать в ответ подписки чужому.

Запуск: .venv/bin/python -m pytest tests/test_vless.py -q
"""

from __future__ import annotations

import json

import pytest

from app import crypto, provisioning
from app.db import SessionLocal, init_db
from app.models import (
    EndpointKind,
    EndpointState,
    NodeEndpoint,
    Provisioning,
    Server,
    User,
    UserEndpointCred,
)
from app.services import endpoints as endpoints_service
from app.services import keys as keys_service
from app.services import xray
from app.services.billing import grant_subscription
from app.services.errors import PanelError

TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "DNS = 1.1.1.1\nMTU = 1280\nJc = 4\nJmin = 40\nJmax = 700\nS1 = 60\nS2 = 90\n"
    "H1 = 10\nH2 = 20\nH3 = 30\nH4 = 40\n"
    "\n[Peer]\nPublicKey = srv\nAllowedIPs = 0.0.0.0/0, ::/0\n"
    "Endpoint = 10.20.30.9:51820\nPersistentKeepalive = 25\n"
)

REALITY_KEYS = "Private key: PRIV-REALITY-KEY\nPublic key: PUB-REALITY-KEY\n"


@pytest.fixture
def node(monkeypatch):
    """Узел, который отвечает на команды вместо настоящего SSH."""
    state = {"config": None, "commands": []}

    def run(server, command):
        state["commands"].append(command)
        if "x25519" in command:
            return REALITY_KEYS
        return ""

    def run_with_input(server, command, payload):
        state["config"] = payload
        state["commands"].append(command)
        return ""

    monkeypatch.setattr(provisioning, "run_over_ssh", run)
    monkeypatch.setattr(provisioning, "run_over_ssh_with_input", run_with_input)
    monkeypatch.setattr(provisioning, "add_peer_over_ssh", lambda *a, **k: None)
    monkeypatch.setattr(provisioning, "remove_peer_over_ssh", lambda *a, **k: None)
    monkeypatch.setattr(provisioning, "dumps_over_ssh", lambda *a, **k: {})
    return state


@pytest.fixture
def server_id():
    init_db()
    with SessionLocal() as db:
        server = Server(
            name="vless-node", country="Нидерланды", host="45.10.10.10", port=51820,
            provisioning=Provisioning.SSH, awg_template=TEMPLATE,
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


def _vless(db, server, port=2053, names=None):
    return xray.create_vless_endpoint(
        db, server, listen_port=port, server_names=names or ["www.google.com"]
    )


# --- заведение точки входа ---------------------------------------------------


def test_reality_private_key_is_encrypted(server_id, node):
    """Приватный ключ Reality в базе — только шифротекстом."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        assert ep.secret_enc and "PRIV-REALITY-KEY" not in ep.secret_enc
        assert crypto.decrypt(ep.secret_enc) == "PRIV-REALITY-KEY"
        # Публичный ключ не секрет — он уходит клиенту.
        assert ep.params["public_key"] == "PUB-REALITY-KEY"
        assert ep.priority > 0, "vless обязан идти после awg"


def test_vless_rejects_busy_port(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        with pytest.raises(PanelError, match="порт"):
            _vless(db, server, port=51820)  # порт самого узла


def test_short_ids_are_never_empty(server_id, node):
    """Пустой short_id означает «принимать любого» — это отключённая проверка."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        assert ep.params["short_ids"]
        assert all(sid for sid in ep.params["short_ids"])


# --- конфиг узла -------------------------------------------------------------


def test_config_blocks_loopback_and_admin_ports(server_id, node):
    """
    Узел и панель — одна машина: клиент VLESS не должен ходить в loopback.

    Без этого он дотянулся бы до API самого xray (добавить себе доступ, снять
    чужие), до панели и до соседнего продукта в докере.
    """
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        config = xray.build_config(db, server)

    routing = config["routing"]
    # Без IPIfNonMatch правила по адресам не применяются к цели-домену.
    assert routing["domainStrategy"] == "IPIfNonMatch"
    blocked = [r for r in routing["rules"] if r.get("outboundTag") == "block"]
    assert any("geoip:private" in (r.get("ip") or []) for r in blocked)
    # Порты администрирования закрыты ТОЛЬКО на самом узле, а не глобально:
    # иначе у vless-клиента пропал бы ssh наружу и чужие сайты на 8443.
    admin = next(r for r in blocked if r.get("port"))
    assert admin["ip"] == ["45.10.10.10/32"]
    assert "10085" in admin["port"]


def test_config_carries_only_live_clients(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "cfg")
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")
        label, identity = cred.label, cred.identity

        config = xray.build_config(db, server)
        inbound = next(i for i in config["inbounds"] if i["tag"] == f"in-{ep.handle}")
        assert [c["email"] for c in inbound["settings"]["clients"]] == [label]
        assert inbound["settings"]["clients"][0]["id"] == identity

        # После отзыва клиент из конфига исчезает.
        xray.revoke_cred(db, cred)
        config = xray.build_config(db, server)
        inbound = next(i for i in config["inbounds"] if i["tag"] == f"in-{ep.handle}")
        assert inbound["settings"]["clients"] == []


def test_apply_config_sends_secrets_through_stdin(server_id, node):
    """Ключи не должны попадать в командную строку — их видно в ps."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        xray.apply_config(db, server)

    assert node["config"], "конфиг обязан уйти через stdin"
    assert "PRIV-REALITY-KEY" in node["config"]
    # И не оказаться ни в одной команде.
    assert all("PRIV-REALITY-KEY" not in cmd for cmd in node["commands"])


# --- креды -------------------------------------------------------------------


def test_cred_uuid_is_encrypted_and_label_is_opaque(server_id, node):
    """
    UUID — только шифротекстом, метка — непрозрачная.

    Метка уезжает в статистику и логи узла: человекочитаемый номер учётки там
    сопоставил бы трафик с конкретным клиентом всякому, кто получил узел.
    """
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "opaque-user")
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")

        assert cred.identity_enc and cred.identity not in (cred.identity_enc or "")
        assert cred.identity_fp and cred.identity_fp != cred.identity
        assert user.public_id not in (cred.label or "")
        assert user.login not in (cred.label or "")


def test_issue_is_idempotent(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "idem")
        first = xray.issue_cred(db, user, server, ep, device_id="phone")
        second = xray.issue_cred(db, user, server, ep, device_id="phone")
        assert first.id == second.id
        assert first.identity == second.identity


def test_share_link_shape(server_id, node):
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "link")
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")
        link = xray.share_link(ep, cred, server)

    assert link.startswith(f"vless://{cred.identity}@45.10.10.10:2053?")
    for needed in ("security=reality", "pbk=PUB-REALITY-KEY", "sni=www.google.com", "flow="):
        assert needed in link


# --- отзыв на всех путях -----------------------------------------------------


def test_device_disconnect_revokes_vless(server_id, node):
    """Отключение устройства снимает и пир, и доступ по второму протоколу."""
    from app.models import Session as Sess
    from app.services import devices as devices_service

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "disc-vless")
        cred = xray.issue_cred(db, user, server, ep, device_id="dev-x")
        cred_id = cred.id
        session = Sess(
            user_id=user.id, token_hash="hash-disc", platform="android",
            device_id="dev-x", expires_at=grant_subscription.__globals__["utcnow"]()
            + __import__("datetime").timedelta(days=1),
        )
        db.add(session)
        db.commit()
        devices_service.disconnect(db, session)

    with SessionLocal() as db:
        assert db.get(UserEndpointCred, cred_id).revoked_at is not None


def test_expired_subscription_revokes_vless(server_id, node):
    """
    Кончилась подписка — доступ VLESS снимается, даже если awg-ключей нет.

    Раньше цикл выходил на первой строке у человека без живых пиров: он
    оставался с работающим вторым протоколом и без подписки.
    """
    import datetime as dt

    from app.models import Subscription, utcnow
    from app.services import traffic

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "expired-vless")
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")
        cred_id = cred.id
        # Подписка кончилась, живых awg-ключей нет вовсе.
        for sub in db.scalars(
            __import__("sqlalchemy").select(Subscription).where(Subscription.user_id == user.id)
        ):
            sub.expires_at = utcnow() - dt.timedelta(days=1)
        for key in user.keys:
            key.revoked_at = utcnow()
        db.commit()
        assert not user.has_access()

        traffic.enforce_access(db)

    with SessionLocal() as db:
        assert db.get(UserEndpointCred, cred_id).revoked_at is not None


def test_block_user_revokes_vless(server_id, node):
    from app.services import users as users_service

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "blocked-vless")
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")
        cred_id = cred.id
        users_service.block_user(db, user, reason="тест")

    with SessionLocal() as db:
        assert db.get(UserEndpointCred, cred_id).revoked_at is not None


def test_no_secrets_key_refuses_to_create_endpoint(server_id, node, monkeypatch):
    """Без ключа шифрования протокол не заводится — честный отказ, не тихая дыра."""
    monkeypatch.setattr(crypto, "available", lambda: False)
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        with pytest.raises(PanelError, match="PANEL_SECRETS_KEY"):
            _vless(db, server, port=2054)


# --- подписка: приоритет и форма ---------------------------------------------


def test_subscription_puts_vless_after_awg(server_id, node):
    """
    Главное требование ТЗ: VLESS идёт ПОСЛЕ awg.

    Проверяется на готовом ответе подписки, а не на константе в коде: клиент
    читает порядок, а не наши намерения. Ряд обязан быть плотным (0..N-1) —
    так его и разбирают клиенты.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import subscription as sub_service

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "prio")
        keys_service.issue_key(db, user, server, device_id="phone")
        raw = sub_service.mint(db, user.id, "phone")

    with TestClient(app) as client:
        body = client.get(f"/s/{raw}").json()

    ours = next(s for s in body["servers"] if s["id"] == server_id)
    protocols = [e["protocol"] for e in ours["endpoints"]]
    priorities = [e["priority"] for e in ours["endpoints"]]

    assert "vless" in protocols, "второй протокол обязан появиться в подписке"
    # Все awg идут раньше любого vless.
    assert protocols.index("vless") > max(
        i for i, p in enumerate(protocols) if p == "awg"
    )
    # Ряд плотный и по возрастанию.
    assert priorities == list(range(len(priorities)))

    vless = next(e for e in ours["endpoints"] if e["protocol"] == "vless")
    assert vless["transport"] == "tcp"
    assert vless["credentials"]["type"] == "vless-reality"
    assert vless["credentials"]["url"].startswith("vless://")
    # Приватный ключ Reality наружу не уходит ни под каким видом.
    assert "PRIV-REALITY-KEY" not in json.dumps(body)


def test_subscription_without_vless_is_unchanged(server_id, node):
    """Пока точек входа VLESS нет, ответ ровно такой же, как в фазе 1."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import subscription as sub_service

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        user = _user(db, "awg-only")
        keys_service.issue_key(db, user, server, device_id="phone")
        raw = sub_service.mint(db, user.id, "phone")

    with TestClient(app) as client:
        body = client.get(f"/s/{raw}").json()

    ours = next(s for s in body["servers"] if s["id"] == server_id)
    assert {e["protocol"] for e in ours["endpoints"]} == {"awg"}
    assert [e["priority"] for e in ours["endpoints"]] == list(
        range(len(ours["endpoints"]))
    )


# --- учёт трафика ------------------------------------------------------------


def test_vless_traffic_counts_and_survives_daemon_restart(server_id, node, monkeypatch):
    """
    Расход VLESS попадает в общий счётчик человека.

    И отдельно: счётчики xray живут в памяти и обнуляются перезапуском демона.
    Значение, уехавшее вниз, обязано считаться приростом с нуля — иначе первый
    же перезапуск дал бы отрицательную дельту и потерю всей истории.
    """
    from app.models import GB

    stats = {"value": 0}

    def run(server, command):
        if "x25519" in command:
            return REALITY_KEYS
        if "statsquery" in command:
            return json.dumps(
                {
                    "stat": [
                        {"name": f"user>>>{stats['label']}>>>traffic>>>uplink",
                         "value": str(stats["value"])},
                        # downlink опущен намеренно: xray не печатает нули, и
                        # парсер обязан считать это нулём, а не падать.
                    ]
                }
            )
        return ""

    monkeypatch.setattr(provisioning, "run_over_ssh", run)

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "traffic-vless")
        user_id = user.id
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")
        stats["label"] = cred.label

        # Первый замер: гигабайт.
        stats["value"] = GB
        xray.sync_traffic(db, server)

    with SessionLocal() as db:
        assert db.get(User, user_id).traffic_used_bytes == GB

    # Демон перезапустили — счётчик обнулился и пошёл заново.
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        stats["value"] = 100
        xray.sync_traffic(db, server)

    with SessionLocal() as db:
        # Прибавилось ровно 100, а не отрицательная разница.
        assert db.get(User, user_id).traffic_used_bytes == GB + 100


# --- регрессии находок ревью -------------------------------------------------


def test_revoke_reaches_the_node(server_id, node):
    """
    Отзыв обязан доехать до узла, а не остаться в базе.

    Иначе «доступ закрыт» существует только в панели: UUID остаётся в конфиге и
    в живом демоне, и человек ходит через VPN без подписки, пока администратор
    не нажмёт кнопку руками.
    """
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server, port=2061)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "revoke-reaches")
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")
        label = cred.label
        assert label in (node["config"] or ""), "выдача обязана доехать до узла"

        node["config"] = None
        xray.revoke_for_user(db, user.id)

    assert node["config"], "отзыв обязан переписать конфиг на узле"
    assert label not in node["config"], "отозванный клиент обязан исчезнуть с узла"


def test_failed_push_is_healed_by_sync_and_not_advertised(server_id, monkeypatch):
    """
    Узел не ответил — доступ не рекламируется, но и не теряется.

    Две вещи разом: подписка не отдаёт ссылку, которой демон не знает (иначе
    она выглядит рабочей и молча не подключается), и запись не откатывается —
    иначе каждый запрос плодил бы новый UUID при недоступном узле.
    """
    state = {"fail": True, "config": None}

    def run(server, command):
        if "x25519" in command:
            return REALITY_KEYS
        return ""

    def run_with_input(server, command, payload):
        if state["fail"]:
            raise RuntimeError("узел не ответил")
        state["config"] = payload
        return ""

    monkeypatch.setattr(provisioning, "run_over_ssh", run)
    monkeypatch.setattr(provisioning, "run_over_ssh_with_input", run_with_input)

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = _vless(db, server, port=2062)
        ep.state = EndpointState.ACTIVE
        db.commit()
        user = _user(db, "healed")
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")
        ep_id, cred_id = ep.id, cred.id

        # Запись цела, но наружу её не отдают: на узле её нет.
        assert db.get(UserEndpointCred, cred_id).revoked_at is None
        assert not xray.is_on_node(db.get(NodeEndpoint, ep_id))

        # Повторная выдача НЕ плодит новый UUID.
        again = xray.issue_cred(db, user, server, db.get(NodeEndpoint, ep_id), device_id="phone")
        assert again.id == cred_id

        # Узел ожил — обход досылает конфиг сам, без вмешательства человека.
        state["fail"] = False
        xray.sync_pending(db, server)
        assert xray.is_on_node(db.get(NodeEndpoint, ep_id))
        assert state["config"], "sync_pending обязан записать конфиг"


def test_config_survives_domain_host(server_id, node):
    """host узла может быть доменом — в routing.ip домен кладёт демон."""
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        server.host = "nl.example.com"
        db.commit()
        ep = _vless(db, server, port=2063)
        ep.state = EndpointState.ACTIVE
        db.commit()
        config = xray.build_config(db, server)

    for rule in config["routing"]["rules"]:
        for value in rule.get("ip") or []:
            assert "example.com" not in value, "домен в routing.ip недопустим"
    # Приватные адреса всё равно закрыты — защита не потерялась.
    assert any("geoip:private" in (r.get("ip") or []) for r in config["routing"]["rules"])


def test_front_mode_listens_loopback_and_advertises_external_port(server_id, node):
    """
    Режим «за фронтом nginx»: слушаем петлю, принимаем PROXY, рекламируем 443.

    Снаружи 443 держит nginx (чтобы сайты пережили падение xray), а донорский
    SNI он заворачивает в этот inbound на 127.0.0.1:8444. Клиенту в подписке
    должен уйти внешний порт 443, а не порт петли.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import subscription as sub_service

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        ep = xray.create_vless_endpoint(
            db, server, listen_port=8444, server_names=["www.google.com"],
            listen_addr="127.0.0.1", accept_proxy=True, advertise_port=443,
            handle="vless-front-443",
        )
        ep.state = EndpointState.ACTIVE
        db.commit()

        config = xray.build_config(db, server)
        inbound = next(i for i in config["inbounds"] if i["tag"] == "in-vless-front-443")
        assert inbound["listen"] == "127.0.0.1"
        assert inbound["port"] == 8444
        assert inbound["streamSettings"]["tcpSettings"]["acceptProxyProtocol"] is True

        user = _user(db, "front")
        keys_service.issue_key(db, user, server, device_id="phone")
        cred = xray.issue_cred(db, user, server, ep, device_id="phone")
        # Ссылка и подписка несут внешний 443, а не 8444.
        link = xray.share_link(ep, cred, server)
        assert ":443?" in link and ":8444" not in link
        raw = sub_service.mint(db, user.id, "phone")

    with TestClient(app) as client:
        body = client.get(f"/s/{raw}").json()
    v = next(e for e in body["servers"][0]["endpoints"] if e["protocol"] == "vless")
    assert v["port"] == 443
