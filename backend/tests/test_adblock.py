"""
«Без рекламы»: тумблер в кабинете и DNS в конфигах.

Включил — DNS в конфиге AmneziaWG и у запасного пути ведёт на адрес узла;
выключил — прежние резолверы. Настройка одна на человека, действует во
всех конфигах и не трогает других.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import provisioning
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Provisioning, Server, User

GB = 1024**3


@pytest.fixture(scope="module")
def client():
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(Server).where(Server.name == "adblock-de")) is None:
            db.add(
                Server(
                    name="adblock-de",
                    country="Германия",
                    country_code="DE",
                    host="10.44.44.4",
                    provisioning=Provisioning.SHARED,
                    shared_config="[Interface]\nAddress = 10.0.0.9/32\nDNS = 1.1.1.1, 8.8.8.8\nPrivateKey = x\n\n[Peer]\nPublicKey = y\nEndpoint = 10.44.44.4:51820\nAllowedIPs = 0.0.0.0/0\n",
                )
            )
        db.commit()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def account(client):
    r = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    created = client.post(
        "/api/admin/users",
        json={"name": "Без рекламы", "planCode": "3months", "trafficLimitBytes": 100 * GB},
        headers=headers,
    ).json()
    return created["user"]["login"], created["password"]


def _token(client, account, platform="web"):
    login, password = account
    r = client.post("/api/v1/login", json={"login": login, "password": password, "platform": platform})
    assert r.status_code == 200, r.text
    return r.json()


def test_with_dns_меняет_и_добавляет():
    assert "DNS = 10.1.1.1" in provisioning.with_dns("[Interface]\nAddress = 10.0.0.2/32\nDNS = 1.1.1.1\n", "10.1.1.1")
    assert "DNS = 1.1.1.1" not in provisioning.with_dns("[Interface]\nDNS = 1.1.1.1\n", "10.1.1.1")
    added = provisioning.with_dns("[Interface]\nAddress = 10.0.0.2/32\nMTU = 1280\n", "10.1.1.1")
    assert added.splitlines()[2] == "DNS = 10.1.1.1", added
    assert provisioning.with_dns("[Peer]\nPublicKey = y\n", "10.1.1.1") == "[Peer]\nPublicKey = y\n"


def test_тумблер_и_конфиги(client, account):
    body = _token(client, account)
    assert body["account"]["adblock"] is False
    auth = {"Authorization": f"Bearer {body['token']}"}

    off = client.get("/api/v1/account", headers=auth).json()
    assert off["adblock"] is False

    on = client.post("/api/v1/account/adblock", json={"on": True}, headers=auth)
    assert on.status_code == 200, on.text
    assert on.json()["adblock"] is True

    # Приложение входит заново и получает конфиг с DNS узла.
    app_body = _token(client, account, platform="android")
    assert app_body["account"]["adblock"] is True
    configs = [s["config"] for s in app_body["servers"] if "10.44.44.4" in s["config"]]
    assert configs, app_body["servers"]
    assert "DNS = 10.44.44.4" in configs[0]
    assert "1.1.1.1" not in configs[0]

    # Выключил — прежние резолверы.
    assert client.post("/api/v1/account/adblock", json={"on": False}, headers=auth).json()["adblock"] is False
    app_body = _token(client, account, platform="android")
    configs = [s["config"] for s in app_body["servers"] if "10.44.44.4" in s["config"]]
    assert "DNS = 1.1.1.1, 8.8.8.8" in configs[0]


def test_чужая_настройка_не_задевает(client, account):
    with SessionLocal() as db:
        others = db.scalars(select(User).where(User.login != account[0])).all()
        assert all(not u.adblock_dns for u in others)
