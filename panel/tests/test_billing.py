"""
Проверка пути «оплата → учётка» целиком, на живой базе.

Здесь проверяется не «работает ли код», а конкретные обещания, нарушение
любого из которых стоит денег или доверия:

* двадцать доставок одного вебхука дают одну учётку, а не двадцать;
* повторная покупка на ту же почту продлевает, а не заводит второго;
* платёж с подделанной суммой не выдаёт доступ;
* возврат снимает подписку и пиры;
* пароль не попадает ни в логи, ни в базу открытым текстом.

Запуск: .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    DeliveryJob,
    Order,
    OrderStatus,
    Plan,
    Provisioning,
    Server,
    Subscription,
    User,
    UserKey,
)
from app.payments import mock as mock_provider
from app.services import billing_webhook


@pytest.fixture(scope="module")
def client():
    init_db()
    with SessionLocal() as db:
        # Сервер с общим ключом: провижининг по SSH полез бы в сеть.
        if db.scalar(select(Server).limit(1)) is None:
            db.add(
                Server(
                    name="test-nl",
                    country="Нидерланды",
                    country_code="NL",
                    host="192.0.2.1",
                    provisioning=Provisioning.SHARED,
                    shared_config="[Interface]\nAddress = 10.0.0.2/32\n",
                )
            )
        plan = db.scalar(select(Plan).where(Plan.code == "basic"))
        plan.set_price(30_000)  # 300 ₽ — как в задании
        plan.period_days = 30
        plan.server_limit = 3
        plan.device_limit = 3
        db.commit()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _order(client, email: str, plan_code: str = "basic") -> dict:
    r = client.post("/api/v1/orders", json={"plan_code": plan_code, "email": email})
    assert r.status_code == 201, r.text
    return r.json()


def _deliver_webhook(client, order_id: str, event: str = "succeeded", attempt: int = 1):
    """Одна доставка уведомления — ровно так, как её шлёт провайдер."""
    with SessionLocal() as db:
        order = db.get(Order, order_id)
        body = mock_provider.build_payload(order, event, attempt)
    return client.post(
        "/api/v1/billing/webhook/mock",
        content=body,
        headers={
            mock_provider.SIGNATURE_HEADER: mock_provider.sign(body),
            "Content-Type": "application/json",
        },
    )


# --- витрина ------------------------------------------------------------------


def test_plans_come_from_database(client):
    """Цены на сайте берутся из базы, а не из вёрстки."""
    r = client.get("/api/v1/plans")
    assert r.status_code == 200
    plans = {p["code"]: p for p in r.json()}
    assert plans["basic"]["price_kopecks"] == 30_000
    assert plans["basic"]["device_limit"] == 3
    # Непубличный тариф на витрину не попадает.
    assert "trial" not in plans


# --- главное обещание: один платёж — одна учётка ------------------------------


def test_twenty_deliveries_give_exactly_one_account(client):
    order = _order(client, "one@example.com")

    for attempt in range(1, 21):
        r = _deliver_webhook(client, order["id"], attempt=attempt)
        # Провайдеру всегда 200: на 500 он начнёт долбить эндпоинт.
        assert r.status_code == 200, r.text

    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.email == "one@example.com")))
        assert len(users) == 1, f"учёток создано {len(users)}, ожидалась одна"

        subs = list(db.scalars(select(Subscription).where(Subscription.user_id == users[0].id)))
        assert len(subs) == 1, f"подписок создано {len(subs)}, ожидалась одна"

        # Письмо тоже одно: двадцать одинаковых писем — это тоже дубль.
        jobs = list(db.scalars(select(DeliveryJob).where(DeliveryJob.user_id == users[0].id)))
        assert len(jobs) == 1

        assert db.get(Order, order["id"]).status == OrderStatus.PAID.value


def test_status_endpoint_shows_credentials_once_paid(client):
    order = _order(client, "creds@example.com")

    before = client.get(f"/api/v1/orders/{order['id']}/status").json()
    assert before["status"] == "pending"
    assert before["login"] is None
    assert before["password"] is None

    _deliver_webhook(client, order["id"])

    after = client.get(f"/api/v1/orders/{order['id']}/status").json()
    assert after["status"] == "paid"
    assert after["login"].startswith("pv")
    assert len(after["login"]) == 9
    # Пароль из трёх групп по четыре символа: k3np-7hqm-2rxa
    assert len(after["password"].split("-")) == 3
    assert after["expires_at"] is not None


# --- повторная покупка --------------------------------------------------------


def test_second_purchase_extends_instead_of_creating_second_user(client):
    first = _order(client, "renew@example.com")
    _deliver_webhook(client, first["id"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "renew@example.com"))
        user_id, login = user.id, user.login
        password_hash = user.password_hash
        expires_first = user.active_subscription().expires_at

    second = _order(client, "renew@example.com")
    _deliver_webhook(client, second["id"])

    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.email == "renew@example.com")))
        assert len(users) == 1, "повторная покупка завела второго пользователя"

        user = users[0]
        assert user.id == user_id and user.login == login
        # Пароль при продлении не меняется: иначе человека выкинуло бы из
        # приложения ровно в тот момент, когда он заплатил.
        assert user.password_hash == password_hash

        expires_second = user.active_subscription().expires_at
        added = (expires_second - expires_first).days
        assert added == 30, f"продлили на {added} дней вместо 30"

    # Второе письмо — про продление, без пароля.
    status = client.get(f"/api/v1/orders/{second['id']}/status").json()
    assert status["is_renewal"] is True
    assert status["password"] is None


# --- подделка суммы -----------------------------------------------------------


def test_tampered_amount_is_rejected(client):
    order = _order(client, "fraud@example.com")

    with SessionLocal() as db:
        row = db.get(Order, order["id"])
        body = mock_provider.build_payload(row)

    # Ровно то, что сделал бы нападающий: сумма другая, подпись пересчитана.
    tampered = body.replace(b'"amount":"300.00"', b'"amount":"1.00"')
    assert tampered != body

    r = client.post(
        "/api/v1/billing/webhook/mock",
        content=tampered,
        headers={
            mock_provider.SIGNATURE_HEADER: mock_provider.sign(tampered),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200
    assert r.json()["result"] == billing_webhook.AMOUNT_MISMATCH

    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "fraud@example.com")) is None
        failed = db.get(Order, order["id"])
        assert failed.status == OrderStatus.FAILED.value
        assert "сумма не совпала" in failed.failure_reason


def test_unsigned_webhook_is_forbidden(client):
    order = _order(client, "unsigned@example.com")
    with SessionLocal() as db:
        body = mock_provider.build_payload(db.get(Order, order["id"]))

    r = client.post("/api/v1/billing/webhook/mock", content=body)
    assert r.status_code == 403

    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "unsigned@example.com")) is None


# --- возврат ------------------------------------------------------------------


def test_refund_cancels_subscription_and_revokes_peers(client):
    order = _order(client, "refund@example.com")
    _deliver_webhook(client, order["id"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "refund@example.com"))
        assert user.has_access()

        # Пир заводим руками: тестовый сервер работает на общем ключе, а он
        # отдельных записей не создаёт. Проверяем именно снятие пира, и для
        # этого пир должен существовать.
        db.add(
            UserKey(
                user_id=user.id,
                server_id=db.scalar(select(Server.id)),
                config="[Interface]\n",
                public_key="test-public-key",
                address="10.0.0.5/32",
            )
        )
        db.commit()

    r = _deliver_webhook(client, order["id"], event="refund")
    assert r.status_code == 200

    with SessionLocal() as db:
        assert db.get(Order, order["id"]).status == OrderStatus.REFUNDED.value
        user = db.scalar(select(User).where(User.email == "refund@example.com"))
        assert not user.has_access()
        assert all(sub.is_cancelled for sub in user.subscriptions)
        assert all(key.revoked_at is not None for key in user.keys)


# --- пароль не утекает --------------------------------------------------------


def test_password_is_never_stored_or_logged_in_plaintext(client, caplog):
    caplog.set_level(logging.DEBUG)

    order = _order(client, "secret@example.com")
    _deliver_webhook(client, order["id"])
    password = client.get(f"/api/v1/orders/{order['id']}/status").json()["password"]
    assert password

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "secret@example.com"))
        # Ни хэш, ни шифротекст не содержат пароля как подстроки.
        assert password not in user.password_hash
        assert user.password_hint is None
        assert user.password_enc and password not in user.password_enc

        # Обход очереди доставки — и тоже без пароля в логах.
        from app.services import delivery

        delivery.run_once(db)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert password not in logged, "пароль попал в лог"


def test_admin_reveal_writes_audit(client, auth):
    order = _order(client, "reveal@example.com")
    _deliver_webhook(client, order["id"])
    password = client.get(f"/api/v1/orders/{order['id']}/status").json()["password"]

    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.email == "reveal@example.com"))

    r = client.post(f"/api/admin/users/{user_id}/reveal", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["password"] == password

    log = client.get("/api/admin/audit", params={"action": "user.password_reveal"}, headers=auth)
    assert log.status_code == 200
    assert any(row["action"] == "user.password_reveal" for row in log.json())


# --- ручная выдача ------------------------------------------------------------


def test_manual_fulfilment_when_webhook_never_arrived(client, auth):
    order = _order(client, "manual@example.com")

    r = client.post(f"/api/admin/orders/{order['id']}/fulfil", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "manual@example.com")) is not None

    # Запоздавший вебхук не должен создать вторую учётку.
    _deliver_webhook(client, order["id"])
    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.email == "manual@example.com")))
        assert len(users) == 1


# --- защита от перебора -------------------------------------------------------


def test_login_is_rate_limited(client):
    order = _order(client, "brute@example.com")
    _deliver_webhook(client, order["id"])
    login = client.get(f"/api/v1/orders/{order['id']}/status").json()["login"]

    codes = [
        client.post("/api/v1/login", json={"login": login, "password": "wrong"}).status_code
        for _ in range(7)
    ]
    assert 429 in codes, f"перебор не остановлен: {codes}"
    # Несуществующий логин отвечает так же, как неверный пароль.
    ghost = client.post("/api/v1/login", json={"login": "pv0000000", "password": "wrong"})
    assert ghost.status_code in (401, 429)


# --- заказы и лимит устройств -------------------------------------------------


def test_account_shows_devices_and_no_technical_fields(client):
    order = _order(client, "account@example.com")
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    r = client.post(
        "/api/v1/login",
        json={
            "login": status["login"],
            "password": status["password"],
            "platform": "web",
            "device_id": "browser-1",
            "device_name": "Chrome",
        },
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    account = client.get("/api/v1/account", headers={"Authorization": f"Bearer {token}"})
    assert account.status_code == 200
    body = account.json()
    assert body["login"] == status["login"]
    assert body["device_limit"] == 3
    assert len(body["devices"]) == 1
    # В кабинете нет ни ключей, ни конфигов — только срок и устройства.
    assert "config" not in account.text and "PrivateKey" not in account.text


def test_device_limit_drops_oldest_session(client):
    order = _order(client, "devices@example.com")
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    def login(device: str) -> str:
        r = client.post(
            "/api/v1/login",
            json={
                "login": status["login"],
                "password": status["password"],
                "device_id": device,
                "device_name": device,
            },
        )
        assert r.status_code == 200, r.text
        return r.json()["token"]

    tokens = [login(f"dev-{i}") for i in range(4)]

    # Тариф даёт три устройства: самое старое отвязано, новое работает.
    first = client.get("/api/v1/account", headers={"Authorization": f"Bearer {tokens[0]}"})
    last = client.get("/api/v1/account", headers={"Authorization": f"Bearer {tokens[-1]}"})
    assert first.status_code == 401
    assert last.status_code == 200
    assert len(last.json()["devices"]) == 3


def test_order_rate_limit_mechanism(client):
    """
    Сам ограничитель заказов — на своих числах.

    Через HTTP его не проверить, не мешая остальным тестам: они ходят с
    того же адреса и делят с ним счётчик.
    """
    from app.services import ratelimit

    with SessionLocal() as db:
        key = "test:orders:203.0.113.7"
        allowed = sum(1 for _ in range(12) if ratelimit.hit(db, key, limit=10, window_minutes=60))
        assert allowed == 10, "ограничитель пропустил больше десяти заказов в час"
        # Счётчик привязан к ключу: сосед по адресу не страдает.
        assert ratelimit.hit(db, "test:orders:198.51.100.9", limit=10, window_minutes=60).allowed


def test_pending_orders_expire(client):
    import datetime as dt

    from app.models import utcnow
    from app.services import orders as orders_service

    order = _order(client, "stale@example.com")
    with SessionLocal() as db:
        row = db.get(Order, order["id"])
        row.created_at = utcnow() - dt.timedelta(hours=48)
        db.commit()
        orders_service.expire_stale(db)
        assert db.get(Order, order["id"]).status == OrderStatus.EXPIRED.value
