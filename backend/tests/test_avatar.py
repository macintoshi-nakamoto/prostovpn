"""
Аватарка из Telegram для приложения: адрес в ответе входа и сама картинка.

Сеть к Telegram подменяется целиком: тесты считают вызовы и проверяют,
что кэш действительно избавляет бота от повторных походов.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Provisioning, Server, User
from app.security import hash_password
from app.services import avatars

PASSWORD = "avatar-pass-1"
TG_ID = 555_000_777
PHOTO = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


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
                    host="10.20.30.1",
                    provisioning=Provisioning.SHARED,
                    shared_config="[Interface]\nAddress = 10.0.0.2/32\n",
                )
            )
        for login, tg in (("ava-plain", None), ("ava-tg", TG_ID)):
            if db.scalar(select(User).where(User.login == login)) is None:
                db.add(User(login=login, password_hash=hash_password(PASSWORD), telegram_id=tg))
        db.commit()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_TELEGRAM_BOT_TOKEN", "12345:avatar-test-token")
    monkeypatch.setenv("PANEL_AVATAR_CACHE_DIR", str(tmp_path / "avatars"))
    settings.cache_clear()
    yield
    settings.cache_clear()


class FakeTelegram:
    """Bot API в двух вызовах: список фото и адрес файла."""

    def __init__(self, photos: bool = True):
        self.photos = photos
        self.calls: list[str] = []

    def get(self, method: str, **params):
        self.calls.append(method)
        if method == "getUserProfilePhotos":
            if not self.photos:
                return {"total_count": 0, "photos": []}
            return {
                "total_count": 1,
                "photos": [[
                    {"file_id": "small", "width": 160, "height": 160},
                    {"file_id": "medium", "width": 320, "height": 320},
                    {"file_id": "large", "width": 640, "height": 640},
                ]],
            }
        if method == "getFile":
            assert params["file_id"] == "medium", "нужен самый мелкий размер, который не мылится"
            return {"file_path": "photos/file_1.jpg"}
        raise AssertionError(method)

    def file(self, file_path: str) -> bytes:
        self.calls.append("file:" + file_path)
        return PHOTO


def _token(client, login: str) -> str:
    r = client.post(
        "/api/v1/login",
        json={"login": login, "password": PASSWORD, "platform": "android", "app_version": "1.3.0"},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _login_body(client, login: str) -> dict:
    r = client.post("/api/v1/login", json={"login": login, "password": PASSWORD, "platform": "android"})
    assert r.status_code == 200, r.text
    return r.json()


def test_no_telegram_no_avatar(client, monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(avatars, "_telegram_get", fake.get)
    monkeypatch.setattr(avatars, "_telegram_file", fake.file)

    body = _login_body(client, "ava-plain")
    assert body["account"]["avatar_url"] is None

    r = client.get("/api/v1/account/avatar", headers={"Authorization": f"Bearer {body['token']}"})
    assert r.status_code == 404
    assert fake.calls == [], "без привязки к Telegram к боту ходить незачем"


def test_avatar_served_and_cached(client, monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(avatars, "_telegram_get", fake.get)
    monkeypatch.setattr(avatars, "_telegram_file", fake.file)

    body = _login_body(client, "ava-tg")
    assert body["account"]["avatar_url"].endswith("/api/v1/account/avatar")
    auth = {"Authorization": f"Bearer {body['token']}"}

    first = client.get("/api/v1/account/avatar", headers=auth)
    assert first.status_code == 200, first.text
    assert first.headers["content-type"].startswith("image/jpeg")
    assert first.headers["cache-control"].startswith("private")
    assert first.content == PHOTO
    assert fake.calls == ["getUserProfilePhotos", "getFile", "file:photos/file_1.jpg"]

    second = client.get("/api/v1/account/avatar", headers=auth)
    assert second.status_code == 200
    assert second.content == PHOTO
    assert len(fake.calls) == 3, "второй раз — из кэша, бота не трогаем"


def test_no_photo_is_remembered(client, monkeypatch):
    fake = FakeTelegram(photos=False)
    monkeypatch.setattr(avatars, "_telegram_get", fake.get)
    monkeypatch.setattr(avatars, "_telegram_file", fake.file)
    auth = {"Authorization": f"Bearer {_token(client, 'ava-tg')}"}

    assert client.get("/api/v1/account/avatar", headers=auth).status_code == 404
    assert client.get("/api/v1/account/avatar", headers=auth).status_code == 404
    assert fake.calls == ["getUserProfilePhotos"], "отсутствие фото тоже помним"


def test_avatar_requires_token(client):
    assert client.get("/api/v1/account/avatar").status_code == 401


def test_telegram_failure_is_not_an_error(client, monkeypatch):
    def boom(method: str, **params):
        raise RuntimeError("Telegram лёг")

    monkeypatch.setattr(avatars, "_telegram_get", boom)
    auth = {"Authorization": f"Bearer {_token(client, 'ava-tg')}"}
    r = client.get("/api/v1/account/avatar", headers=auth)
    assert r.status_code == 404, "отказ Telegram — это «нет фото», а не 500"
