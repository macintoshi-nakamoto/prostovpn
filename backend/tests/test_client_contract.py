"""
Контракт клиентского API глазами приложения.

Проверяет ровно те имена полей, которые читает PanelAuthController в
desktop/client/ui/controllers/panelAuthController.cpp. Переименование поля
на стороне панели ломает вход в приложении молча — тут это видно сразу.

Запуск: .venv/Scripts/python.exe -m pytest tests/test_client_contract.py -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Окружение задаётся в conftest.py, см. пояснение там.
from app.db import SessionLocal, init_db
from app.main import app
from app.models import GB, Provisioning, Server

# Поля, которые приложение читает из ответа. Список — копия того, что
# разбирает C++: если что-то отсюда пропадёт, вход перестанет работать.
ACCOUNT_FIELDS = {"public_id", "login", "name"}
SUBSCRIPTION_FIELDS = {"active", "plan", "days_left", "traffic_used_bytes", "traffic_limit_bytes"}
SERVER_FIELDS = {"config", "country", "city", "country_code", "name"}
# Полей с адресом и ключом в ответе быть не должно.
FORBIDDEN_SERVER_FIELDS = {"host", "port", "key", "public_key", "address", "ssh_host"}


@pytest.fixture(scope="module")
def client():
    init_db()
    with SessionLocal() as db:
        db.add(
            Server(
                name="test-de",
                country="Германия",
                country_en="Germany",
                city="Франкфурт",
                country_code="DE",
                # Частный адрес, а не документационный: узлы с адресами из
                # документационных диапазонов панель клиентам не отдаёт.
                host="10.20.30.7",
                provisioning=Provisioning.SHARED,
                shared_config="[Interface]\nAddress = 10.0.0.9/32\nPrivateKey = x\n",
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
        json={"name": "Клиент Windows", "planCode": "plus", "trafficLimitBytes": 100 * GB},
        headers=headers,
    ).json()
    return created["user"]["login"], created["password"], headers


def test_login_shape_matches_client(client, account):
    login, password, _ = account

    # Ровно то тело, которое шлёт PanelAuthController::login.
    r = client.post(
        "/api/v1/login",
        json={"login": login, "password": password, "platform": "windows", "app_version": "2.2.0"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert "token" in body and body["token"]
    assert ACCOUNT_FIELDS <= set(body["account"])
    assert SUBSCRIPTION_FIELDS <= set(body["subscription"])

    assert body["servers"], "с активной подпиской серверы обязаны прийти"
    for server in body["servers"]:
        assert SERVER_FIELDS <= set(server)
        leaked = FORBIDDEN_SERVER_FIELDS & set(server)
        assert not leaked, f"наружу ушло лишнее: {leaked}"
        # Конфиг нужен туннелю, поэтому он есть — но это единственное
        # техническое поле, и на экране оно не показывается.
        assert server["config"].startswith("[Interface]")


def test_unlimited_traffic_is_null_not_zero(client):
    """Безлимит приложение узнаёт по null, а не по нулю: ноль — это «всё выбрано»."""
    r = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    created = client.post(
        "/api/admin/users", json={"name": "Безлимитный", "planCode": "plus"}, headers=headers
    ).json()
    client.post(
        f"/api/admin/users/{created['user']['id']}/traffic-limit",
        json={"unlimited": True},
        headers=headers,
    )

    body = client.post(
        "/api/v1/login", json={"login": created["user"]["login"], "password": created["password"]}
    ).json()
    assert body["subscription"]["traffic_limit_bytes"] is None


def test_token_flow_servers_and_logout(client, account):
    login, password, _ = account
    token = client.post("/api/v1/login", json={"login": login, "password": password}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    # PanelAuthController::refresh
    servers = client.get("/api/v1/servers", headers=auth)
    assert servers.status_code == 200
    assert SUBSCRIPTION_FIELDS <= set(servers.json()["subscription"])
    assert servers.json()["servers"]

    # PanelAuthController::logout
    assert client.post("/api/v1/logout", headers=auth).status_code == 200
    # После выхода токен недействителен — приложение обязано попросить вход.
    assert client.get("/api/v1/servers", headers=auth).status_code == 401


def test_revoked_token_reports_401(client, account):
    """
    Администратор гасит сессию — приложение должно получить 401.

    На этом построен выход по чужой команде: PanelAuthController на 401
    очищает сохранённую сессию и показывает экран входа.
    """
    login, password, headers = account
    token = client.post("/api/v1/login", json={"login": login, "password": password}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/servers", headers=auth).status_code == 200

    users = client.get("/api/admin/users", params={"q": login}, headers=headers).json()
    detail = client.get(f"/api/admin/users/{users[0]['id']}", headers=headers).json()
    live = [s for s in detail["sessions"] if s["revokedAt"] is None]
    assert live
    client.delete(f"/api/admin/users/{users[0]['id']}/sessions/{live[0]['id']}", headers=headers)

    assert client.get("/api/v1/servers", headers=auth).status_code == 401


def test_error_detail_is_human_readable(client):
    """Приложение показывает detail как есть — он должен быть по-русски."""
    r = client.post("/api/v1/login", json={"login": "nobody", "password": "nothing"})
    assert r.status_code == 401
    detail = r.json()["detail"]
    assert detail == "неверный логин или пароль"
