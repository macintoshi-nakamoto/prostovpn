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
from app.models import DeliveryJob, Provisioning, Server, User
from app import services
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


def _init_data(
    telegram_id: int,
    *,
    token: str = BOT_TOKEN,
    age: int = 0,
    username: str | None = None,
    first_name: str = "Тест",
) -> str:
    profile: dict[str, object] = {"id": telegram_id, "first_name": first_name}
    if username:
        profile["username"] = username
    pairs = {
        "auth_date": str(int(time.time()) - age),
        "query_id": "AAF-test",
        "user": json.dumps(profile, ensure_ascii=False),
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


def test_signup_takes_login_from_telegram_username(client):
    r = client.post(
        "/api/v1/login/telegram",
        json={"init_data": _init_data(555_000_001, username="VanZero")},
    )
    assert r.status_code == 200, r.text
    # Юзернейм человек помнит наизусть — логин должен совпасть с ним,
    # только строчными: Telegram регистра не различает, а логин различает.
    assert r.json()["account"]["login"] == "vanzero"


def test_signup_without_username_falls_back_to_the_name(client):
    r = client.post(
        "/api/v1/login/telegram",
        json={"init_data": _init_data(555_000_002, first_name="Пётр")},
    )
    assert r.status_code == 200, r.text
    login = r.json()["account"]["login"]
    # Юзернейм в Telegram не обязателен: тогда прежний путь — транслит
    # имени со случайным хвостом, потому что имена не уникальны.
    assert login.startswith("petr-")
    assert login != "petr"


def test_taken_username_does_not_collide(client):
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.login == "busy")) is None:
            db.add(User(login="busy", password_hash=hash_password("irrelevant-2")))
            db.commit()

    r = client.post(
        "/api/v1/login/telegram",
        json={"init_data": _init_data(555_000_003, username="busy")},
    )
    assert r.status_code == 200, r.text
    login = r.json()["account"]["login"]
    # Юзернейм могли сменить, а учётка с этим логином осталась: занятый
    # логин не повод отказать в регистрации.
    assert login != "busy"
    assert login.startswith("busy-")


def test_username_is_remembered_for_the_admin_panel(client):
    client.post(
        "/api/v1/login/telegram",
        json={"init_data": _init_data(555_000_004, username="marker_one")},
    )
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_id == 555_000_004))
        assert user is not None
        assert user.login == "marker_one"
        assert user.telegram_username == "marker_one"


def _make_user(login: str, password: str, telegram_id: int | None = None, email: str | None = None):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == login))
        if user is None:
            user = User(login=login, password_hash=hash_password(password), telegram_id=telegram_id)
            user.set_email(email)
            db.add(user)
            db.commit()


def _login(client, login: str, password: str, telegram_id: int):
    return client.post(
        "/api/v1/login",
        json={
            "login": login,
            "password": password,
            "platform": "web",
            "init_data": _init_data(telegram_id),
        },
    )


def test_password_reset_closes_telegram_login_until_password_is_typed_once(client):
    """
    Сброс пароля по письму рвёт сессии и ссылки-подписки — и вход по одной
    подписи Telegram тоже: привязку мог сделать тот, кто пароль однажды
    узнал. Один вход с новым паролем из мини-приложения открывает его обратно.
    """
    _make_user("tg-reset", "old-password-1", telegram_id=777_000_222, email="reset@example.test")
    assert client.post("/api/v1/login/telegram", json={"init_data": _init_data(777_000_222)}).status_code == 200

    with SessionLocal() as db:
        assert services.passwords.request(db, "reset@example.test")
        token = db.scalar(
            select(DeliveryJob.payload)
            .where(DeliveryJob.template == "password_reset", DeliveryJob.target == "reset@example.test")
            .order_by(DeliveryJob.id.desc())
        )
    r = client.post("/api/v1/password/reset", json={"token": token, "password": "new-password-2"})
    assert r.status_code == 200, r.text

    # Подпись Telegram одна больше не пускает — и новую учётку не заводит.
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(777_000_222)})
    assert r.status_code == 401, r.text
    assert r.headers.get("X-Error-Code") == "tg_relink"
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.telegram_id == 777_000_222)).login == "tg-reset"

    # Хозяин Telegram вошёл с новым паролем — замок снят.
    assert _login(client, "tg-reset", "new-password-2", 777_000_222).status_code == 200
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(777_000_222)})
    assert r.status_code == 200, r.text
    assert r.json()["account"]["login"] == "tg-reset"


def test_stranger_who_linked_with_a_leaked_password_is_cut_off_by_a_password_change(client):
    _make_user("tg-victim", "leaked-password-1")
    # Чужой Telegram привязался чужим паролем.
    assert _login(client, "tg-victim", "leaked-password-1", 666_000_001).status_code == 200
    assert client.post("/api/v1/login/telegram", json={"init_data": _init_data(666_000_001)}).status_code == 200

    # Хозяин меняет пароль с сайта.
    owner = client.post("/api/v1/login", json={"login": "tg-victim", "password": "leaked-password-1", "platform": "web"})
    auth = {"Authorization": f"Bearer {owner.json()['token']}"}
    r = client.post(
        "/api/v1/account/password",
        json={"current_password": "leaked-password-1", "new_password": "fresh-password-2"},
        headers=auth,
    )
    assert r.status_code == 200, r.text

    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(666_000_001)})
    assert r.status_code == 401
    assert r.headers.get("X-Error-Code") == "tg_relink"

    # Хозяин входит из своего Telegram с новым паролем — его Telegram
    # занимает место чужого, чужой в эту учётку больше не попадает.
    assert _login(client, "tg-victim", "fresh-password-2", 555_000_778).status_code == 200
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == "tg-victim"))
        assert user.telegram_id == 555_000_778
        assert user.telegram_relink_at is None
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(555_000_778)})
    assert r.status_code == 200 and r.json()["account"]["login"] == "tg-victim"
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(666_000_001)})
    assert r.status_code != 200 or r.json()["account"]["login"] != "tg-victim"


def test_stranger_cannot_reopen_the_lock_with_the_old_password(client):
    _make_user("tg-victim2", "leaked-password-1")
    assert _login(client, "tg-victim2", "leaked-password-1", 666_000_002).status_code == 200
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == "tg-victim2"))
        services.set_password(db, user, "fresh-password-2")
    assert _login(client, "tg-victim2", "leaked-password-1", 666_000_002).status_code == 401
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(666_000_002)})
    assert r.status_code == 401 and r.headers.get("X-Error-Code") == "tg_relink"


def _attached_letters(email: str) -> list[DeliveryJob]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(DeliveryJob)
                .where(DeliveryJob.template == "telegram_attached", DeliveryJob.target == email)
                .order_by(DeliveryJob.id)
            )
        )


def test_owner_with_email_is_told_about_a_new_telegram(client):
    """
    Привязка Telegram — вход без пароля. Хозяин почты должен узнать о ней:
    если привязался не он, письмо подскажет сменить пароль.
    """
    _make_user("tg-mailed", "password-one-1", email="mailed@example.test")
    r = client.post(
        "/api/v1/login",
        json={
            "login": "tg-mailed",
            "password": "password-one-1",
            "platform": "web",
            "init_data": _init_data(444_000_001, username="Evil_Twin"),
        },
    )
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == "tg-mailed"))
        assert user.telegram_id == 444_000_001
    jobs = _attached_letters("mailed@example.test")
    assert len(jobs) == 1 and jobs[0].payload == "@Evil_Twin"

    # Повторный вход с тем же Telegram — не новость, второго письма нет.
    assert _login(client, "tg-mailed", "password-one-1", 444_000_001).status_code == 200
    assert len(_attached_letters("mailed@example.test")) == 1


def test_owner_can_see_and_detach_telegram_from_the_account(client):
    """
    Кабинет показывает привязку и умеет её снять. После отвязки подпись
    Telegram не пускает и НЕ заводит новую учётку; вход с паролем из
    мини-приложения возвращает привязку без письма — это свой же Telegram.
    """
    _make_user("tg-detach", "password-two-2", email="detach@example.test")
    assert _login(client, "tg-detach", "password-two-2", 444_000_002).status_code == 200
    assert len(_attached_letters("detach@example.test")) == 1

    web = client.post("/api/v1/login", json={"login": "tg-detach", "password": "password-two-2", "platform": "web"})
    auth = {"Authorization": f"Bearer {web.json()['token']}"}
    tma = client.post("/api/v1/login/telegram", json={"init_data": _init_data(444_000_002)})
    assert tma.status_code == 200, tma.text
    tma_auth = {"Authorization": f"Bearer {tma.json()['token']}"}

    account = client.get("/api/v1/account", headers=auth).json()
    assert account["telegram_linked"] is True

    r = client.delete("/api/v1/account/telegram", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "relogin_required": False}

    account = client.get("/api/v1/account", headers=auth).json()
    assert account["telegram_linked"] is False and account["telegram_username"] is None
    assert client.get("/api/v1/account", headers=tma_auth).status_code == 401, "сессия мини-приложения отозвана"
    assert client.delete("/api/v1/account/telegram", headers=auth).status_code == 404
    assert client.delete("/api/v1/account/telegram", headers=auth).headers.get("X-Error-Code") == "tg_not_linked"

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == "tg-detach"))
        assert user.telegram_id is None and user.telegram_detached_id == 444_000_002

    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(444_000_002)})
    assert r.status_code == 401, r.text
    assert r.headers.get("X-Error-Code") == "tg_detached"
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.telegram_id == 444_000_002)) is None, "дубль заведён"

    assert _login(client, "tg-detach", "password-two-2", 444_000_002).status_code == 200
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == "tg-detach"))
        assert user.telegram_id == 444_000_002 and user.telegram_detached_id is None
    assert len(_attached_letters("detach@example.test")) == 1, "возврат своего Telegram — без письма"
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(444_000_002)})
    assert r.status_code == 200 and r.json()["account"]["login"] == "tg-detach"


def test_detach_from_the_mini_app_asks_to_sign_in_again(client):
    _make_user("tg-detach-tma", "password-three-3")
    assert _login(client, "tg-detach-tma", "password-three-3", 444_000_003).status_code == 200
    tma = client.post("/api/v1/login/telegram", json={"init_data": _init_data(444_000_003)})
    auth = {"Authorization": f"Bearer {tma.json()['token']}"}
    r = client.delete("/api/v1/account/telegram", headers=auth)
    assert r.status_code == 200 and r.json()["relogin_required"] is True
    assert client.get("/api/v1/account", headers=auth).status_code == 401


def test_first_password_from_mini_app_keeps_telegram_login_open(client):
    """
    Учётка из Telegram придумывает себе пароль впервые — прямо в
    мини-приложении. Это не «чужой пароль», и вход по подписи закрывать не
    за что: иначе человека тут же выкинуло бы на форму входа. А вот смена
    уже существующего пароля закрывает вход по Telegram, как и раньше.
    """
    _make_user("tg-first", "seed-password-0", telegram_id=777_000_555)
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(777_000_555)})
    assert r.status_code == 200, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.telegram_id == 777_000_555))
        u.credentials_set_at = None
        db.commit()

    r = client.post("/api/v1/account/credentials", json={"password": "my-own-password-1"}, headers=auth)
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(777_000_555)})
    assert r.status_code == 200, "первый пароль не должен закрывать вход по Telegram"

    # Смена уже существующего пароля — закрывает вход по подписи до входа с паролем.
    auth = {"Authorization": f"Bearer {r.json()['token']}"}
    r = client.post(
        "/api/v1/account/password",
        json={"current_password": "my-own-password-1", "new_password": "my-own-password-2"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/login/telegram", json={"init_data": _init_data(777_000_555)})
    assert r.status_code == 401 and r.headers.get("X-Error-Code") == "tg_relink"
