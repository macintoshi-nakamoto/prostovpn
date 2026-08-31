from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Provisioning, Server, User
from app.security import hash_password

BOT_TOKEN = "12345:test-tg-bot-token"


@pytest.fixture(scope="module")
def client():
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(Server).limit(1)) is None:
            db.add(
                Server(
                    name="test-nl",
                    country="Нидерланды",
                    country_code="NL",
                    city="Амстердам",
                    host="10.20.30.1",
                    provisioning=Provisioning.SHARED,
                    shared_config="[Interface]\nAddress = 10.0.0.2/32\n",
                )
            )
        if db.scalar(select(User).where(User.login == "tg-linked")) is None:
            db.add(
                User(
                    login="tg-linked",
                    password_hash=hash_password("irrelevant-1"),
                    telegram_id=777_000_111,
                )
            )
        db.commit()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _bot_token(monkeypatch):
    # settings() под lru_cache: без сброса токен закешируется пустым
    monkeypatch.setenv("PANEL_TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    settings.cache_clear()
    yield
    settings.cache_clear()


def _init_data(telegram_id: int, *, token: str = BOT_TOKEN, age: int = 0) -> str:
    pairs = {
        "auth_date": str(int(time.time()) - age),
        "query_id": "AAF-test",
        "user": json.dumps({"id": telegram_id, "first_name": "Тест"}, ensure_ascii=False),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_linked_telegram_signs_in_without_password(client):
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(777_000_111)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account"]["login"] == "tg-linked"

    auth = {"Authorization": f"Bearer {body['token']}"}
    account = client.get("/api/v1/account", headers=auth)
    assert account.status_code == 200
    # сессия мини-приложения — не устройство и слот не занимает
    assert account.json()["devices"] == []


def test_bad_signature_is_rejected(client):
    forged = _init_data(777_000_111, token="12345:another-token")
    r = client.post("/api/v1/login/telegram", json={"init_data": forged})
    assert r.status_code == 401
    assert r.headers.get("X-Error-Code") == "tg_invalid"


def test_stale_init_data_is_rejected(client):
    r = client.post(
        "/api/v1/login/telegram",
        json={"init_data": _init_data(777_000_111, age=3 * 24 * 3600)},
    )
    assert r.status_code == 401
    assert r.headers.get("X-Error-Code") == "tg_stale"


def test_unlinked_telegram_gets_fresh_account(client):
    """
    Незнакомый Telegram больше не упирается в 404, а получает свою учётку.

    Подпись initData уже удостоверила личность — спрашивать логин с паролем
    не за чем, панель их выдаёт сама. Прежний ответ «этот Telegram не
    привязан» отправлял человека искать бота, хотя бот и мини-приложение —
    один и тот же вход.
    """
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(999_999_999)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account"]["login"]
    assert body["token"]

    # Второй заход тем же Telegram попадает в ту же учётку, а не плодит новую.
    again = client.post("/api/v1/login/telegram", json={"init_data": _init_data(999_999_999)})
    assert again.status_code == 200, again.text
    assert again.json()["account"]["public_id"] == body["account"]["public_id"]


def test_without_bot_token_login_is_disabled(client, monkeypatch):
    monkeypatch.delenv("PANEL_TELEGRAM_BOT_TOKEN", raising=False)
    settings.cache_clear()
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(777_000_111)})
    assert r.status_code == 503
    assert r.headers.get("X-Error-Code") == "tg_disabled"
