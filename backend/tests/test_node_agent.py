"""
Агент на узле: приём снимков, живость по протоколам, оповещения.

Как и в test_node_alerts: адресаты — только из настройки, в базе лежит
живой человек-приманка, которому ничего приходить не должно.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    EndpointKind,
    EndpointState,
    NodeEndpoint,
    Provisioning,
    Server,
    User,
    UserEndpointCred,
    UserKey,
    utcnow,
)
from app.security import hash_password
from app.services import agent, alerts

NODE_IP = "10.77.77.7"

PEER_A = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
PEER_B = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="

# То, что выдаёт `awg show awg0 dump`: строка интерфейса, потом пиры
# (pubkey, psk, endpoint, allowed-ips, handshake, rx, tx, keepalive).
DUMP = (
    "PRIVKEY\tPUBKEY\t51820\toff\n"
    f"{PEER_A}\t(none)\t1.2.3.4:5\t10.8.3.2/32\t1757000000\t1000\t2000\toff\n"
    f"{PEER_B}\t(none)\t(none)\t10.8.3.3/32\t0\t0\t0\toff\n"
)


def snapshot(*, xray_ok: bool = True, hy2_ok: bool = True) -> dict:
    return {
        "agent": "0.1.0",
        "at": 1757000000,
        "hostname": "lt-test",
        "uptime_s": 3600,
        "load": [0.1, 0.2, 0.3],
        "mem_total_kb": 2000000,
        "mem_avail_kb": 1500000,
        "awg": {"awg0": {"ok": True, "port": 51820, "peers": 2, "dump": DUMP}},
        "xray": {
            "ok": xray_ok,
            "listen_ok": xray_ok,
            "api_ok": True,
            "online_count": 1,
            "stats": '{"stat":[{"name":"user>>>u1>>>traffic>>>uplink","value":10}]}',
            "online": '{"users":["user>>>u1>>>online"]}',
            "ips": "@@U@@u1\n{\"ips\":{\"5.6.7.8\":1757000000}}\n",
            "error": "" if xray_ok else "порт 443 не слушается",
        },
        "hy2": {"ok": hy2_ok, "port": 10086, "traffic": {"u1": {"tx": 1, "rx": 2}}, "online": {"u1": 1}},
        "services": {"prosto-xray": "active" if xray_ok else "failed", "prosto-hy2": "active", "awg-quick@awg0": "active"},
        "took_ms": 120,
    }


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def node():
    with SessionLocal() as db:
        server = Server(
            name="agent-lt",
            country="Литва",
            country_code="LT",
            host=NODE_IP,
            provisioning=Provisioning.SSH,
            is_active=True,
        )
        db.add(server)
        db.add(User(login="agent-victim", password_hash=hash_password("x"), telegram_id=999778))
        db.flush()
        # Точка входа VLESS с Hysteria2: без неё панель и не ждёт от узла
        # ни xray, ни Hysteria2, и их падение не считается бедой.
        db.add(
            NodeEndpoint(
                server_id=server.id,
                kind=EndpointKind.VLESS,
                handle="vless0",
                listen_port=443,
                state=EndpointState.ACTIVE,
                params={"hy2": {"port": 443}},
            )
        )
        db.commit()
        token = agent.issue_token(db, server)
        server_id = server.id
    yield server_id, token
    with SessionLocal() as db:
        row = db.get(Server, server_id)
        if row is not None:
            db.delete(row)
        victim = db.scalar(select(User).where(User.login == "agent-victim"))
        if victim is not None:
            db.delete(victim)
        db.commit()


def _post(client, token, body, ip=NODE_IP):
    return client.post(
        "/api/v1/node/report",
        json=body,
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": ip},
    )


def test_без_токена_и_с_чужим_токеном(client, node):
    _, token = node
    assert client.post("/api/v1/node/report", json=snapshot()).status_code == 401
    assert _post(client, "not-a-token", snapshot()).status_code == 401
    assert _post(client, token, snapshot(), ip="9.9.9.9").status_code == 403, "токен с чужого адреса не работает"


def test_снимок_принят_и_виден_в_админке(client, node):
    server_id, token = node
    r = _post(client, token, snapshot())
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["interval"] >= 5

    with SessionLocal() as db:
        server = db.get(Server, server_id)
        assert server.agent_seen_at is not None
        assert server.agent_version == "0.1.0"
        assert server.agent_trouble_since is None
        summary = agent.health(server)
        assert summary["awg_ok"] and summary["xray_ok"] and summary["hy2_ok"]
        assert summary["peers"] == 2
        assert summary["online_vless"] == 1 and summary["online_hy2"] == 1
        assert summary["stale"] is False
        assert summary["trouble"] is None

        from app.admin_api.mappers import server_out

        out = server_out(db, server)
        assert out.agent is not None and out.agent.peers == 2 and out.agent.xray_ok is True


def _keyholder(server_id: int) -> int:
    """Человек с ключом AmneziaWG (PEER_A) и учёткой xray/Hysteria2 (u1) на узле."""
    with SessionLocal() as db:
        user = User(login="agent-keyholder", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        db.add(
            UserKey(
                user_id=user.id, server_id=server_id, device_id="test-device", config="[Interface]",
                public_key=PEER_A, address="10.8.3.2/32", rx_bytes=900, tx_bytes=1900,
            )
        )
        endpoint = db.scalar(select(NodeEndpoint).where(NodeEndpoint.server_id == server_id))
        db.add(UserEndpointCred(user_id=user.id, server_id=server_id, endpoint_id=endpoint.id, label="u1"))
        db.commit()
        return user.id


def _drop_keyholder() -> None:
    with SessionLocal() as db:
        holder = db.scalar(select(User).where(User.login == "agent-keyholder"))
        if holder is not None:
            db.delete(holder)
            db.commit()


def test_снимок_зачисляет_трафик_и_живость(client, node):
    """
    Второй шаг агента: снимок — источник счётчиков и живости. Байты awg и
    xray абсолютные (дельта от базы), Hysteria2 — дельты с пометкой cleared.
    """
    server_id, token = node
    user_id = _keyholder(server_id)
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        server.down_since = utcnow() - dt.timedelta(minutes=10)
        db.commit()
    try:
        body = snapshot()
        body["hy2"]["cleared"] = True
        assert _post(client, token, body).status_code == 200
        with SessionLocal() as db:
            # awg: (1000+2000) − (900+1900) = 200; xray uplink 10; hy2 1+2 = 3
            assert db.get(User, user_id).traffic_used_bytes == 213
            key = db.scalar(select(UserKey).where(UserKey.public_key == PEER_A))
            assert key.rx_bytes == 1000 and key.tx_bytes == 2000
            assert key.last_handshake_at is not None
            cred = db.scalar(
                select(UserEndpointCred).where(UserEndpointCred.server_id == server_id, UserEndpointCred.label == "u1")
            )
            assert cred.rx_bytes == 10 and cred.last_seen_at is not None
            server = db.get(Server, server_id)
            assert server.down_since is None and server.last_ok_at is not None
            assert server.traffic_error is None and server.traffic_synced_at is not None
            assert agent.covered(server) == {"awg", "xray", "hy2"}
            assert agent.awg_dumps(server) == {"awg0": DUMP}
            assert agent.recent_ips() == {user_id: {"5.6.7.8"}}

        # Тот же снимок ещё раз: абсолютные счётчики не изменились, дельт нет.
        body["hy2"]["traffic"] = {}
        assert _post(client, token, body).status_code == 200
        with SessionLocal() as db:
            assert db.get(User, user_id).traffic_used_bytes == 213

        # Без пометки cleared байты Hysteria2 абсолютные — не наши: их
        # снимает обход по SSH, а снимок только отмечает онлайн.
        body["hy2"]["cleared"] = False
        body["hy2"]["traffic"] = {"u1": {"tx": 100, "rx": 100}}
        assert _post(client, token, body).status_code == 200
        with SessionLocal() as db:
            assert db.get(User, user_id).traffic_used_bytes == 213
            assert agent.covered(db.get(Server, server_id)) == {"awg", "xray"}
    finally:
        _drop_keyholder()


def test_обход_по_ssh_молчит_пока_снимок_свежий(client, node, monkeypatch):
    """Свежий снимок — по SSH за счётчиками не ходим; агент замолчал —
    обход возвращается и честно видит, что узел не отвечает."""
    server_id, token = node
    from app import provisioning
    from app.services import traffic, xray

    calls: list[str] = []

    def no_ssh(*args, **kwargs):
        calls.append("ssh")
        raise RuntimeError("SSH недоступен")

    monkeypatch.setattr(provisioning, "dumps_over_ssh", no_ssh)
    monkeypatch.setattr(provisioning, "run_over_ssh", no_ssh)
    monkeypatch.setattr(xray, "sync_pending", lambda db, server: False)

    body = snapshot()
    body["hy2"]["cleared"] = True
    assert _post(client, token, body).status_code == 200
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        rounds = traffic.sweep_server(db, server)
        assert all("skipped" in r for r in rounds), rounds
        assert calls == []
        db.refresh(server)
        assert server.down_since is None

        server.agent_seen_at = utcnow() - dt.timedelta(minutes=5)
        db.commit()
        assert agent.covered(server) == set()
        traffic.sweep_server(db, server)
        assert calls, "без свежего снимка обход должен сходить по SSH"
        db.refresh(server)
        assert server.down_since is not None


def test_служба_легла_оповещение_только_админам(client, node, monkeypatch):
    server_id, token = node
    monkeypatch.setattr(settings(), "alert_chat_ids", "111, 222")
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(alerts.telegram, "send", lambda chat_id, text: sent.append((chat_id, text)))

    assert _post(client, token, snapshot(xray_ok=False)).status_code == 200
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        assert server.agent_trouble_since is not None
        # только что легло — рано
        assert agent.check_agents(db) == []
        server.agent_trouble_since = utcnow() - dt.timedelta(minutes=4)
        db.commit()
        assert agent.check_agents(db) == ["trouble:agent-lt"]
        assert agent.check_agents(db) == [], "второй раз о том же не пишем"

    assert sorted(chat for chat, _ in sent) == [111, 222]
    assert 999778 not in {chat for chat, _ in sent}
    assert "Reality" in sent[0][1] and "порт 443" in sent[0][1]

    # всё вернулось — одно сообщение о восстановлении и тем же адресатам
    sent.clear()
    assert _post(client, token, snapshot()).status_code == 200
    with SessionLocal() as db:
        assert agent.check_agents(db) == ["fine:agent-lt"]
        server = db.get(Server, server_id)
        assert server.agent_alert_sent_at is None and server.agent_trouble_since is None
    assert sorted(chat for chat, _ in sent) == [111, 222]


def test_новый_токен_гасит_старый(client, node):
    server_id, token = node
    with SessionLocal() as db:
        fresh = agent.issue_token(db, db.get(Server, server_id))
    assert _post(client, token, snapshot()).status_code == 401
    assert _post(client, fresh, snapshot()).status_code == 200


def test_снимок_не_json_объект(client, node):
    _, token = node
    r = client.post(
        "/api/v1/node/report",
        content=json.dumps([1, 2, 3]),
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": NODE_IP, "Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_перебор_из_под_vpn_не_запирает_сам_узел(client, node):
    """Люди из-под VPN приходят адресом узла. Их промахи входа не должны
    ни запирать адрес узла, ни мешать снимкам агента и авторизации Hysteria2."""
    _, token = node
    for i in range(60):
        r = client.post(
            "/api/v1/login",
            json={"login": f"vpn-guess-{i}", "password": "wrong"},
            headers={"X-Forwarded-For": NODE_IP},
        )
        assert r.status_code != 429, f"адрес узла заперт на {i}-м промахе"

    assert _post(client, token, snapshot()).status_code == 200
    r = client.post(
        "/api/v1/hy2/auth",
        json={"addr": "x", "auth": "nope-nope-nope-1"},
        headers={"X-Forwarded-For": NODE_IP},
    )
    assert r.status_code == 200 and r.json() == {"ok": False}


def test_ошибка_с_узла_в_оповещении_экранируется(client, node, monkeypatch):
    server_id, token = node
    monkeypatch.setattr(settings(), "alert_chat_ids", "111")
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(alerts.telegram, "send", lambda chat_id, text: sent.append((chat_id, text)))

    body = snapshot(xray_ok=False)
    body["xray"]["error"] = "<i>x</i>"
    assert _post(client, token, body).status_code == 200
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        server.agent_trouble_since = utcnow() - dt.timedelta(minutes=4)
        db.commit()
        assert agent.check_agents(db) == ["trouble:agent-lt"]
    assert "&lt;i&gt;x&lt;/i&gt;" in sent[0][1] and "<i>x</i>" not in sent[0][1]
