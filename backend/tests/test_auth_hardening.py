from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Order, RateLimit, Session, User, utcnow
from app.payments import mock as mock_provider
from app.services import auth as auth_service
from app.services import ratelimit


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


def _fake_request(headers: dict[str, str], peer: str | None = "203.0.113.5"):
    from fastapi import Request

    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 12345) if peer else None,
    }
    return Request(scope)


def test_forwarded_for_takes_the_address_nginx_appended():
    from app.security import client_ip

    # Заголовок честен только из-под нашего nginx (петля).
    request = _fake_request({"X-Forwarded-For": "1.2.3.4, 198.51.100.77"}, peer="127.0.0.1")
    assert client_ip(request) == "198.51.100.77"


def test_forwarded_for_from_a_stranger_is_ignored():
    from app.security import client_ip

    # Прямое соединение мимо nginx: X-Forwarded-For пишет сам клиент, и по
    # нему нельзя ни обходить лимиты, ни притворяться узлом.
    request = _fake_request({"X-Forwarded-For": "1.2.3.4, 198.51.100.77"}, peer="203.0.113.5")
    assert client_ip(request) == "203.0.113.5"


def test_client_ip_falls_back_to_peer_without_header():
    from app.security import client_ip

    assert client_ip(_fake_request({})) == "203.0.113.5"


def test_client_ip_never_returns_something_too_long_for_the_column():
    from app.security import client_ip

    long_zone = "fe80::1%" + "A" * 300
    value = client_ip(_fake_request({"X-Forwarded-For": long_zone}, peer="127.0.0.1"))
    assert value == "fe80::1", "zone id должен отбрасываться вместе со своей длиной"

    junk = client_ip(_fake_request({"X-Forwarded-For": "не адрес вовсе"}, peer="127.0.0.1"))
    assert junk == "127.0.0.1", "мусор в заголовке — берём адрес соединения"

    for header in (long_zone, "A" * 500, "1.2.3.4" * 40):
        got = client_ip(_fake_request({"X-Forwarded-For": header}))
        assert got is None or len(got) <= 45, got


def test_admin_login_is_rate_limited(client, auth):
    try:
        codes = [
            client.post(
                "/api/admin/login", json={"login": "admin", "password": f"wrong-{i}"}
            )
            for i in range(7)
        ]
        throttled = [r for r in codes if r.status_code == 429]
        assert throttled, f"перебор не остановлен: {[r.status_code for r in codes]}"
        assert any(r.status_code == 401 for r in codes)
        assert "мин" in throttled[0].json()["detail"], throttled[0].text
    finally:
        with SessionLocal() as db:
            for key in (
                auth_service._admin_key("admin", None),
                auth_service._admin_name_key("admin"),
                auth_service._admin_ip_key(None),
            ):
                ratelimit.clear(db, key)

    ok = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    assert ok.status_code == 200, ok.text


def test_token_is_extended_while_the_app_is_used(client, auth):
    created = client.post(
        "/api/admin/users", json={"name": "Продление Токена", "planCode": "3months"}, headers=auth
    ).json()

    r = client.post(
        "/api/v1/login",
        json={"login": created["user"]["login"], "password": created["password"]},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    soon = utcnow() + dt.timedelta(days=2)
    with SessionLocal() as db:
        user = db.get(User, created["user"]["id"])
        session = sorted(user.sessions, key=lambda s: s.id)[-1]
        session.expires_at = soon
        db.commit()
        session_id = session.id

    r = client.get("/api/v1/servers", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        after = db.get(Session, session_id).expires_at
    assert after > soon, "токен активного пользователя не продлился"


def _paid_order(client, email: str) -> str:
    r = client.post("/api/v1/orders", json={"plan_code": "basic", "email": email})
    assert r.status_code == 201, r.text
    order_id = r.json()["id"]

    with SessionLocal() as db:
        body = mock_provider.build_payload(db.get(Order, order_id))
    r = client.post(
        "/api/v1/billing/webhook/mock",
        content=body,
        headers={
            mock_provider.SIGNATURE_HEADER: mock_provider.sign(body),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    return order_id


def test_order_status_never_serves_password_or_email(client):
    """Номер заказа гуляет по ссылкам возврата и переводам TON — по нему
    нельзя получить ни пароль, ни почту. Пароль уходит письмом и ботом."""
    order_id = _paid_order(client, "window@example.com")

    fresh = client.get(f"/api/v1/orders/{order_id}/status").json()
    assert fresh["status"] == "paid"
    assert fresh["login"], "логин и срок остаются: по ним человек пишет в поддержку"
    assert fresh["password"] is None
    assert fresh.get("email") is None

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        order.paid_at = utcnow() - dt.timedelta(hours=1)
        db.commit()

    stale = client.get(f"/api/v1/orders/{order_id}/status").json()
    assert stale["login"] and stale["password"] is None


def test_pending_order_status_does_not_tell_whether_email_is_a_customer(client):
    """Ожидающий заказ не выдаёт «продление или новая учётка» — это был бы
    способ проверить, есть ли у адреса аккаунт."""
    _paid_order(client, "known@example.com")
    r = client.post(
        "/api/v1/orders",
        json={"plan_code": "basic", "email": "known@example.com"},
        headers={"X-Forwarded-For": "10.9.9.9"},
    )
    assert r.status_code == 201, r.text
    body = client.get(f"/api/v1/orders/{r.json()['id']}/status").json()
    assert body["status"] == "pending"
    assert body["is_renewal"] is False and body["login"] is None and body.get("email") is None


def test_encrypt_refuses_the_default_key(monkeypatch):
    from app import crypto
    from app.config import INSECURE_DEFAULT_SECRET, Settings

    default = Settings(secrets_key=INSECURE_DEFAULT_SECRET)
    monkeypatch.setattr(crypto, "settings", lambda: default)

    with pytest.raises(crypto.SecretsUnavailable):
        crypto.encrypt("тайна")
    assert crypto.encrypt_or_none("тайна") is None


def test_decrypt_still_reads_blobs_written_with_the_old_key(monkeypatch):
    from app import crypto
    from app.config import INSECURE_DEFAULT_SECRET, Settings

    default = Settings(secrets_key=INSECURE_DEFAULT_SECRET)
    monkeypatch.setattr(crypto, "settings", lambda: default)

    import base64
    import hashlib

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(INSECURE_DEFAULT_SECRET.encode()).digest()
    nonce = b"\x00" * 12
    blob = nonce + AESGCM(key).encrypt(nonce, "старый-пароль".encode(), None)
    token = "pv1." + base64.urlsafe_b64encode(blob).decode()

    assert crypto.decrypt(token) == "старый-пароль"


def test_rate_limit_counts_every_attempt():
    key = "test:hardening:198.51.100.200"
    with SessionLocal() as db:
        ratelimit.clear(db, key)
        allowed = sum(1 for _ in range(9) if ratelimit.hit(db, key, limit=5, window_minutes=15))
        assert allowed == 5, f"пропущено {allowed} попыток вместо пяти"

        row = db.execute(select(RateLimit).where(RateLimit.key == key)).scalar_one()
        row.window_start = utcnow() - dt.timedelta(minutes=30)
        row.locked_until = None
        db.commit()
        assert ratelimit.hit(db, key, limit=5, window_minutes=15).allowed
        ratelimit.clear(db, key)


def test_login_by_name_survives_a_changing_address(client, auth):
    created = client.post(
        "/api/admin/users", json={"name": "Пул Адресов", "planCode": "3months"}, headers=auth
    ).json()
    login = created["user"]["login"]

    codes = [
        client.post(
            "/api/v1/login",
            json={"login": login, "password": "wrong"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        ).status_code
        for i in range(1, 30)
    ]
    assert 429 in codes, f"перебор с пула адресов не остановлен: {codes}"

    with SessionLocal() as db:
        ratelimit.clear(db, auth_service._login_name_key(login))


def test_change_password_is_throttled_per_user(client):
    r = client.post("/api/v1/register", json={"login": "pwchange-probe", "password": "probe-pass-123"})
    assert r.status_code == 201, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    codes = []
    for _ in range(6):
        r = client.post(
            "/api/v1/account/password",
            json={"current_password": "ne-tot", "new_password": "novyi-parol-12"},
            headers=headers,
        )
        codes.append(r.status_code)
    assert codes == [400] * 5 + [429], codes
    assert r.headers.get("Retry-After")

    # Под замком и верный пароль не проходит — как у замка входа.
    r = client.post(
        "/api/v1/account/password",
        json={"current_password": "probe-pass-123", "new_password": "novyi-parol-12"},
        headers=headers,
    )
    assert r.status_code == 429


def test_password_hashing_is_gated():
    import threading
    import time

    from app import security

    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    class Stub:
        def verify(self, stored, password):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return True

    original = security._ARGON2
    security._ARGON2 = Stub()
    try:
        threads = [
            threading.Thread(target=security.verify_password, args=("x", "$argon2id$stub"))
            for _ in range(12)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        security._ARGON2 = original
    assert 1 <= state["peak"] <= 4, state


NODE_HOST = "10.66.66.6"


@pytest.fixture()
def node_server():
    from app.models import Provisioning, Server

    with SessionLocal() as db:
        server = Server(name="shared-exit", country="X", country_code="XX", host=NODE_HOST,
                        provisioning=Provisioning.SSH, is_active=True)
        db.add(server)
        db.commit()
        server_id = server.id
    yield NODE_HOST
    with SessionLocal() as db:
        row = db.get(Server, server_id)
        if row is not None:
            db.delete(row)
            db.commit()


def _misses(client, address: str, count: int) -> list[int]:
    return [
        client.post(
            "/api/v1/login",
            json={"login": f"nobody-{address}-{i}", "password": "wrong"},
            headers={"X-Forwarded-For": address},
        ).status_code
        for i in range(count)
    ]


def test_node_address_is_not_locked_by_someone_elses_misses(client, auth, node_server):
    """Из-под VPN все приходят адресом узла: перебор одного не должен
    запирать вход в кабинет остальным. Для адреса человека замок остаётся."""
    created = client.post(
        "/api/admin/users", json={"name": "За Узлом", "planCode": "3months"}, headers=auth
    ).json()
    login, password = created["user"]["login"], created["password"]

    assert 429 not in _misses(client, node_server, 60)
    r = client.post(
        "/api/v1/login", json={"login": login, "password": password},
        headers={"X-Forwarded-For": node_server},
    )
    assert r.status_code == 200, r.text

    human = "198.51.100.209"
    try:
        codes = _misses(client, human, 60)
        assert 429 in codes, codes
        r = client.post(
            "/api/v1/login", json={"login": login, "password": password},
            headers={"X-Forwarded-For": human},
        )
        assert r.status_code == 429
    finally:
        with SessionLocal() as db:
            ratelimit.clear(db, auth_service._login_ip_key(human))


def test_forgot_password_limit_is_softer_for_the_node_address(client, node_server):
    for i in range(6):
        r = client.post(
            "/api/v1/password/forgot", json={"email": f"vpn-user-{i}@example.test"},
            headers={"X-Forwarded-For": node_server},
        )
        assert r.status_code == 200, (i, r.text)

    human = "198.51.100.210"
    codes = [
        client.post(
            "/api/v1/password/forgot", json={"email": f"home-user-{i}@example.test"},
            headers={"X-Forwarded-For": human},
        ).status_code
        for i in range(6)
    ]
    assert codes == [200] * 5 + [429], codes
