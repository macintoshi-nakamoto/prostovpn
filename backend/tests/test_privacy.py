from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import GB, Provisioning, Server, Session as Sess
from app.security import ip_tag


@pytest.fixture
def client():
    init_db()
    with SessionLocal() as db:
        if db.query(Server).count() == 0:
            db.add(Server(name="nl", country="Нидерланды", host="10.20.30.9",
                          provisioning=Provisioning.SHARED,
                          shared_config="[Interface]\nAddress = 10.0.0.9/32\nPrivateKey = x\n"))
            db.commit()
    with TestClient(app) as c:
        yield c


def _admin(client):
    r = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_login_stores_no_ip(client):
    h = _admin(client)
    u = client.post("/api/admin/users", json={"name": "Аноним", "planCode": "3months"}, headers=h).json()
    client.post("/api/v1/login", json={
        "login": u["user"]["login"], "password": u["password"],
        "platform": "android", "device_id": "priv1", "device_name": "MacBook Ивана",
    }, headers={"X-Forwarded-For": "198.51.100.7"})

    with SessionLocal() as db:
        s = db.query(Sess).filter(Sess.device_id == "priv1").order_by(Sess.id.desc()).first()
        assert s is not None
        assert s.ip is None, "IP входа не должен храниться"
        assert s.device_name is None, "имя устройства не должно храниться"
        assert s.device_id == "priv1"


def test_panel_card_hides_ip_and_device_name(client):
    h = _admin(client)
    u = client.post("/api/admin/users", json={"name": "Клиент", "planCode": "3months"}, headers=h).json()
    client.post("/api/v1/login", json={
        "login": u["user"]["login"], "password": u["password"],
        "platform": "android", "device_id": "priv2", "device_name": "iPhone",
    }, headers={"X-Forwarded-For": "203.0.113.9"})

    card = client.get(f"/api/admin/users/{u['user']['id']}", headers=h).json()
    for sess in card.get("sessions", []):
        assert "ip" not in sess or sess["ip"] is None
        assert "deviceName" not in sess or not sess.get("deviceName")


def test_order_stores_no_ip(client):
    h = _admin(client)
    u = client.post("/api/admin/users", json={"name": "Покупатель", "planCode": "3months"}, headers=h).json()
    from app.models import Order
    client.post("/api/v1/login", json={"login": u["user"]["login"], "password": u["password"]},
                headers={"X-Forwarded-For": "203.0.113.55"})
    with SessionLocal() as db:
        assert all(o.ip is None for o in db.query(Order).all()), "IP заказа не должен храниться"


def test_ip_tag_is_not_reversible_without_salt():
    a, b = ip_tag("198.51.100.7"), ip_tag("203.0.113.9")
    assert a != b
    assert "198.51.100.7" not in a and "203.0.113.9" not in b
    assert ip_tag("198.51.100.7") == a


def test_session_remembers_isp_but_not_ip(client, monkeypatch):
    # Телеметрии связи нужен провайдер человека (через туннель запрос
    # приходит адресом узла) — но именно провайдер, а не адрес.
    from app.services import asn

    monkeypatch.setattr(asn, "isp_name", lambda ip: "MTS PJSC" if ip == "198.51.100.7" else None)
    h = _admin(client)
    u = client.post("/api/admin/users", json={"name": "Провайдер", "planCode": "3months"}, headers=h).json()
    client.post("/api/v1/login", json={
        "login": u["user"]["login"], "password": u["password"],
        "platform": "android", "device_id": "priv-isp",
    }, headers={"X-Forwarded-For": "198.51.100.7"})

    with SessionLocal() as db:
        s = db.query(Sess).filter(Sess.device_id == "priv-isp").order_by(Sess.id.desc()).first()
        assert s is not None
        assert s.ip is None, "адрес не храним"
        assert s.isp == "МТС", "а провайдера — да, в нормализованном виде"
