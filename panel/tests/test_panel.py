"""
Проверки панели. Запуск: python -m pytest panel/tests -q

База — временный SQLite, сеть не трогаем: серверы в тестах только в режиме
общего ключа, автогенерация по SSH требует живого сервера.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile

import pytest

# Настройки читаются при импорте, поэтому задаём до него
_tmpdir = tempfile.mkdtemp()
os.environ["PANEL_DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["PANEL_ADMIN_LOGIN"] = "admin"
os.environ["PANEL_ADMIN_PASSWORD"] = "secret"
os.environ["PANEL_SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app import services  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Provisioning, Server, User  # noqa: E402
from app.provisioning import build_vpn_key, generate_keypair, next_address  # noqa: E402
from app.security import hash_password, verify_password  # noqa: E402

CONFIG = """[Interface]
Address = 10.8.1.3/32
PrivateKey = ALVYdQqp6aZb73z+VDW5vkaGZ9knPujAP6eISaO9Rl0=
MTU = 1280

[Peer]
PublicKey = +YpTmPOnJx9Z9WMpEZDLONmBd/PwvsuY2yaacA2fVhQ=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 89.125.138.227:35335
"""


@pytest.fixture(scope="module", autouse=True)
def _db():
    init_db()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _server(db, name="Швеция", host="89.125.138.227") -> Server:
    server = Server(
        name=name,
        host=host,
        port=35335,
        country="Швеция",
        country_code="SE",
        provisioning=Provisioning.SHARED,
        shared_config=CONFIG,
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return server


# --- пароли ------------------------------------------------------------------


def test_password_roundtrip():
    stored = hash_password("Пароль123")
    assert verify_password("Пароль123", stored)
    assert not verify_password("другой", stored)
    # Соль случайная: одинаковые пароли не дают одинаковый хэш
    assert stored != hash_password("Пароль123")


def test_broken_hash_is_rejected_not_crashed():
    assert not verify_password("что угодно", "мусор")


# --- ключи и адреса ----------------------------------------------------------


def test_keypair_is_valid_wireguard():
    private, public = generate_keypair()
    import base64

    assert len(base64.b64decode(private)) == 32
    assert len(base64.b64decode(public)) == 32
    assert private != public


def test_next_address_skips_taken():
    assert next_address([]) == "10.8.1.2/32"
    assert next_address(["10.8.1.2/32"]) == "10.8.1.3/32"
    assert next_address(["10.8.1.2/32", "10.8.1.3"]) == "10.8.1.4/32"


def test_vpn_key_is_readable_by_the_app():
    """Ключ должен разбираться так же, как его разбирает приложение."""
    import base64
    import json

    key = build_vpn_key("89.125.138.227", CONFIG, 35335)
    assert key.startswith("vpn://")

    payload = key[len("vpn://") :]
    payload += "=" * (-len(payload) % 4)
    data = json.loads(base64.urlsafe_b64decode(payload))

    assert data["hostName"] == "89.125.138.227"
    inner = json.loads(data["containers"][0]["awg"]["last_config"])
    assert inner["config"].startswith("[Interface]")
    assert "Endpoint = 89.125.138.227:35335" in inner["config"]


# --- пользователи ------------------------------------------------------------


def test_create_user_grants_subscription(db):
    user, warnings = services.create_user(db, login="petya", password="pass1234", days=30)
    assert warnings == []
    assert user.has_access()
    assert user.active_subscription().expires_at > services.utcnow()


def test_duplicate_login_is_refused(db):
    services.create_user(db, login="dupe", password="pass1234")
    with pytest.raises(services.PanelError):
        services.create_user(db, login="dupe", password="pass1234")


def test_extension_adds_to_the_tail_not_today(db):
    """Продление не должно съедать оставшиеся дни."""
    user, _ = services.create_user(db, login="extend", password="pass1234", days=10)
    first = user.active_subscription().expires_at
    services.grant_subscription(db, user, days=30)
    db.refresh(user)
    second = user.active_subscription().expires_at
    assert (second - first).days == 30


def test_revoked_user_loses_access(db):
    user, _ = services.create_user(db, login="revoked", password="pass1234", days=30)
    services.revoke_access(db, user)
    db.refresh(user)
    assert not user.has_access()


# --- клиентское API ----------------------------------------------------------


def test_login_returns_key_and_servers(client, db):
    _server(db, name="Швеция-1", host="1.1.1.1")
    services.create_user(db, login="apiuser", password="pass1234", days=30)

    response = client.post(
        "/api/v1/login",
        json={"login": "apiuser", "password": "pass1234", "platform": "windows"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["subscription"]["active"] is True
    assert body["servers"], "сервер есть, но приложению ничего не отдали"
    server = body["servers"][0]
    assert server["config"].startswith("[Interface]")
    assert server["key"].startswith("vpn://")
    assert server["country_code"] == "SE"


def test_wrong_password_is_401(client, db):
    services.create_user(db, login="wrongpass", password="pass1234", days=30)
    response = client.post("/api/v1/login", json={"login": "wrongpass", "password": "нет"})
    assert response.status_code == 401


def test_user_without_subscription_gets_no_servers(client, db):
    _server(db, name="Швеция-2", host="2.2.2.2")
    services.create_user(db, login="nosub", password="pass1234", days=0)

    body = client.post("/api/v1/login", json={"login": "nosub", "password": "pass1234"}).json()
    assert body["subscription"]["active"] is False
    assert body["servers"] == [], "без подписки серверов быть не должно"


def test_new_server_appears_for_existing_user(client, db):
    """Главное требование: добавленный сервер виден всем без ручной раздачи."""
    services.create_user(db, login="seesnew", password="pass1234", days=30)
    token = client.post(
        "/api/v1/login", json={"login": "seesnew", "password": "pass1234"}
    ).json()["token"]

    before = client.get("/api/v1/servers", headers={"Authorization": f"Bearer {token}"}).json()
    _server(db, name="Новый сервер", host="3.3.3.3")
    after = client.get("/api/v1/servers", headers={"Authorization": f"Bearer {token}"}).json()

    assert len(after["servers"]) == len(before["servers"]) + 1
    assert any(s["name"] == "Новый сервер" for s in after["servers"])


def test_token_is_required(client):
    assert client.get("/api/v1/servers").status_code == 401
    # Заголовки только ASCII — кириллица в токене падает ещё в клиенте
    assert client.get("/api/v1/servers", headers={"Authorization": "Bearer made-up"}).status_code == 401


def test_logout_kills_the_token(client, db):
    services.create_user(db, login="logout", password="pass1234", days=30)
    token = client.post(
        "/api/v1/login", json={"login": "logout", "password": "pass1234"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/servers", headers=headers).status_code == 200
    assert client.post("/api/v1/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/servers", headers=headers).status_code == 401


def test_session_is_recorded_for_the_panel(client, db):
    services.create_user(db, login="session", password="pass1234", days=30)
    client.post(
        "/api/v1/login",
        json={"login": "session", "password": "pass1234", "platform": "android", "app_version": "1.0.1"},
    )
    user = db.query(User).filter(User.login == "session").one()
    db.refresh(user)
    assert user.sessions
    assert user.sessions[-1].platform == "android"
    assert user.sessions[-1].app_version == "1.0.1"


# --- деньги ------------------------------------------------------------------


def test_revenue_is_counted_by_day_month_year(db):
    user, _ = services.create_user(db, login="payer", password="pass1234", days=30)
    services.add_payment(db, amount="300.50", user=user, method="карта")
    services.add_payment(db, amount="199.50", user=user, method="карта")

    totals = services.dashboard_totals(db)
    assert float(totals["revenue_day"]) >= 500
    assert float(totals["revenue_month"]) >= 500
    assert float(totals["revenue_year"]) >= 500

    daily = services.revenue_series(db, days=7)
    assert len(daily) == 7
    assert float(daily[-1][1]) >= 500, "сегодняшний день должен быть последним"


def test_negative_payment_is_refused(db):
    with pytest.raises(services.PanelError):
        services.add_payment(db, amount="-100")


def test_old_payment_lands_in_the_right_day(db):
    long_ago = services.utcnow() - dt.timedelta(days=3)
    services.add_payment(db, amount="42", paid_at=long_ago)
    daily = services.revenue_series(db, days=7)
    day = dict(daily)[long_ago.date().isoformat()]
    assert float(day) >= 42


# --- админка -----------------------------------------------------------------


def test_admin_requires_login(client):
    response = client.get("/users", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_admin_can_log_in_and_see_pages(client):
    response = client.post("/login", data={"login": "admin", "password": "secret"}, follow_redirects=False)
    assert response.status_code == 303

    for path in ("/", "/users", "/servers", "/payments"):
        page = client.get(path)
        assert page.status_code == 200, path
        assert "Prosto VPN" in page.text


def test_admin_wrong_password_is_refused(client):
    fresh = TestClient(app)
    response = fresh.post("/login", data={"login": "admin", "password": "нет"})
    assert response.status_code == 401


def test_forged_cookie_is_rejected(client):
    fresh = TestClient(app)
    fresh.cookies.set("panel_session", "1:99999999999:forged-signature")
    assert fresh.get("/users", follow_redirects=False).status_code == 303
