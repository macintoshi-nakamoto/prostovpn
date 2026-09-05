"""Телеметрия подключений: приём отчётов от приложения и сводка для админки."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import ConnectReport, Provisioning, Server
from app.services import telemetry


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def node():
    with SessionLocal() as db:
        server = Server(
            name="tm-node",
            country="Нидерланды",
            country_code="NL",
            host="10.77.0.1",
            provisioning=Provisioning.SHARED,
            shared_config="[Interface]\nAddress = 10.0.0.2/32\n",
        )
        db.add(server)
        db.commit()
        return server.host


@pytest.fixture(scope="module")
def app_token(client, auth):
    created = client.post(
        "/api/admin/users", json={"name": "Телеметрия", "planCode": "3months"}, headers=auth
    ).json()
    r = client.post(
        "/api/v1/login",
        json={
            "login": created["user"]["login"],
            "password": created["password"],
            "platform": "android",
            "app_version": "1.1.11",
            "device_id": "tm-phone",
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _report(**over):
    base = {
        "protocol": "awg",
        "host": "10.77.0.1",
        "port": 51820,
        "ok": False,
        "stage": "handshake",
        "duration_ms": 12000,
        "attempts": 3,
        "error": "no handshake",
        "network": {"kind": "cellular", "operator": "MTS", "country": "RU"},
    }
    base.update(over)
    return base


def test_reports_are_stored_with_session_facts(client, app_token, node):
    r = client.post(
        "/api/v1/telemetry/connect",
        json={
            "reports": [
                _report(),
                _report(protocol="vless", port=443, ok=True, duration_ms=1800, attempts=1, error=None),
                _report(protocol="bogus"),
                _report(network={"kind": "wifi"}, ok=True, duration_ms=900, attempts=1, error=None),
            ]
        },
        headers=app_token,
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 3

    with SessionLocal() as db:
        rows = list(db.query(ConnectReport).order_by(ConnectReport.id))
        assert len(rows) == 3
        assert {row.platform for row in rows} == {"android"}
        assert {row.app_version for row in rows} == {"1.1.11"}
        assert rows[0].server_id is not None and rows[0].operator == "МТС"
        assert rows[1].protocol == "vless" and rows[1].ok is True
        assert rows[2].network_kind == "wifi" and rows[2].operator is None


def test_summary_builds_operator_matrix(client, auth, app_token):
    body = client.get("/api/admin/telemetry", params={"days": 7}, headers=auth).json()
    assert body["reports"] == 3 and body["ok"] == 2
    cells = {(o["operator"], o["protocol"]): o for o in body["operators"]}
    assert cells[("МТС", "awg")]["okPct"] == 0.0
    assert cells[("МТС", "vless")]["okPct"] == 100.0 and cells[("МТС", "vless")]["medianMs"] == 1800
    assert cells[("Wi-Fi", "awg")]["ok"] == 1
    assert body["errors"][0]["error"] == "no handshake"
    assert body["recentFailures"][0]["server"] == "Нидерланды"
    assert body["usersReporting"] == 1 and body["usersNeverOk"] == 0


def test_daily_cap_per_session(client, app_token):
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.models import Session

        session = db.scalar(select(Session).where(Session.device_id == "tm-phone"))
        room = telemetry.MAX_PER_SESSION_DAY
        # добиваем до предела и одну сверху
        accepted = telemetry.store(db, session, [_report()] * (room + 5))
        assert accepted <= telemetry.MAX_PER_REQUEST
    r = client.post("/api/v1/telemetry/connect", json={"reports": [_report()]}, headers=app_token)
    assert r.status_code == 200
    # без токена — отказ
    assert client.post("/api/v1/telemetry/connect", json={"reports": [_report()]}).status_code == 401
