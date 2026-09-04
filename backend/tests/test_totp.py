"""Второй фактор для админки и список адресов у служебной учётки."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import crypto
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Admin
from app.services import totp


def test_totp_codes_match_rfc_vector():
    # RFC 6238, секрет «12345678901234567890» (base32 GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ), T=59 → 287082 (SHA1)
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp.code_at(secret, totp.current_step(59)) == "287082"
    assert totp.verify(secret, "287082", now=59) == 1
    assert totp.verify(secret, "287082", now=59 + 3 * 30) is None, "за окном ±1 шаг код не годится"
    assert totp.verify(secret, "28708", now=59) is None
    assert "otpauth://totp/Prosto%20VPN:admin?secret=" in totp.otpauth_uri("admin", secret)


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


def _login(client, **extra):
    return client.post("/api/admin/login", json={"login": "admin", "password": "admin", **extra})


@pytest.mark.skipif(not crypto.available(), reason="секрет второго фактора живёт под шифром")
def test_second_factor_gates_login_and_rejects_replay(client):
    token = _login(client).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/admin/totp", headers=auth).json() == {"enabled": False, "enabledAt": None, "pending": False}
    setup = client.post("/api/admin/totp/setup", headers=auth).json()
    assert setup["secret"] and setup["otpauthUrl"].startswith("otpauth://totp/")

    # Кривой код не включает.
    r = client.post("/api/admin/totp/enable", json={"code": "000000"}, headers=auth)
    assert r.status_code == 400
    now = time.time()
    good = totp.code_at(setup["secret"], totp.current_step(now))
    r = client.post("/api/admin/totp/enable", json={"code": good}, headers=auth)
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert client.get("/api/admin/me", headers=auth).json()["totpEnabled"] is True

    # Без кода пароль больше не пускает, и панель говорит, что нужен код.
    r = _login(client)
    assert r.status_code == 401 and r.headers.get("X-Error-Code") == "totp_required"
    r = _login(client, code="123456")
    assert r.status_code == 401 and r.headers.get("X-Error-Code") == "totp_invalid"

    # Тот же код, что подтвердил включение, повторно не проходит; следующий шаг — да.
    r = _login(client, code=good)
    assert r.status_code == 401 and r.headers.get("X-Error-Code") == "totp_invalid"
    with SessionLocal() as db:
        admin = db.scalar(select(Admin).where(Admin.login == "admin"))
        admin.totp_last_step -= 2
        db.commit()
    r = _login(client, code=good)
    assert r.status_code == 200, r.text
    fresh = {"Authorization": f"Bearer {r.json()['token']}"}

    # Выключить — только с кодом.
    assert client.post("/api/admin/totp/disable", json={"code": "999999"}, headers=fresh).status_code == 400
    r = client.post("/api/admin/totp/disable", json={"code": good}, headers=fresh)
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert _login(client).status_code == 200


def test_ip_allowlist_keeps_service_account_home(client):
    """Список адресов: с чужого адреса верный пароль отвечает как неверный.
    У тестового клиента адрес не разбирается как IP (None), поэтому
    положительную ветку проверяем на самой модели."""
    with SessionLocal() as db:
        admin = db.scalar(select(Admin).where(Admin.login == "admin"))
        admin.ip_allowlist = "10.66.0.1, 127.0.0.1"
        db.commit()
        assert admin.ip_allowed("10.66.0.1") and admin.ip_allowed("127.0.0.1")
        assert not admin.ip_allowed("1.2.3.4") and not admin.ip_allowed(None)
    try:
        r = _login(client)
        assert r.status_code == 401 and "неверный логин или пароль" in r.text
    finally:
        with SessionLocal() as db:
            admin = db.scalar(select(Admin).where(Admin.login == "admin"))
            admin.ip_allowlist = None
            db.commit()
    assert _login(client).status_code == 200
