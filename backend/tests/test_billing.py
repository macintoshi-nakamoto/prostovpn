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
                    host="10.20.30.1",
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


# --- почему «вошёл, а ничего не работает» ------------------------------------


def test_demo_servers_are_never_given_to_clients(client):
    """
    Узел с адресом из документационного диапазона клиенту не достаётся.

    Так выглядела реальная поломка: в базе остались демонстрационные узлы с
    адресами RFC 5737, панель показывала их включёнными, приложение честно
    получало страну в списке — и подключение уходило в никуда. Показать
    такой узел хуже, чем не показать: вместо понятного «серверы
    настраиваются» человек получает вечное ожидание.
    """
    from app.models import Provisioning, Server

    with SessionLocal() as db:
        db.add(
            Server(
                name="demo-broken",
                country="Демо",
                country_code="XX",
                host="203.0.113.15",  # документационный диапазон
                provisioning=Provisioning.SHARED,
                shared_config="[Interface]\nAddress = 10.0.0.9/32\n",
                is_active=True,
            )
        )
        db.commit()

    order = _order(client, "demo-check@example.com")
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    r = client.post(
        "/api/v1/login", json={"login": status["login"], "password": status["password"]}
    )
    assert r.status_code == 200, r.text
    body = r.json()

    names = [s["name"] for s in body["servers"]]
    assert "Демо" not in names, "демонстрационный узел ушёл клиенту"

    with SessionLocal() as db:
        from sqlalchemy import delete

        db.execute(delete(Server).where(Server.name == "demo-broken"))
        db.commit()


def test_empty_server_list_explains_itself(client):
    """
    Пустой список без объяснения — это и был весь баг.

    Человек оплачивал, вводил логин и пароль, вход проходил успешно — и
    дальше тишина. Ни приложение, ни панель не могли сказать, в чём дело.
    Теперь API обязан прислать причину вместе с пустым списком.
    """
    from app.models import Server

    order = _order(client, "notice@example.com")
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    with SessionLocal() as db:
        servers = list(db.scalars(select(Server)))
        was = {s.id: s.is_active for s in servers}
        for s in servers:
            s.is_active = False
        db.commit()

    try:
        r = client.post(
            "/api/v1/login", json={"login": status["login"], "password": status["password"]}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["servers"] == []
        assert body["notice"], "пустой список пришёл без объяснения"
        assert "недоступн" in body["notice"].lower() or "настраива" in body["notice"].lower()
    finally:
        with SessionLocal() as db:
            for s in db.scalars(select(Server)):
                s.is_active = was.get(s.id, True)
            db.commit()


def test_notice_names_the_real_reason_when_subscription_ended(client):
    """Кончилась подписка — так и сказать, а не «серверы недоступны»."""
    import datetime as dt

    from app.models import utcnow

    order = _order(client, "expired-notice@example.com")
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    r = client.post(
        "/api/v1/login", json={"login": status["login"], "password": status["password"]}
    )
    token = r.json()["token"]

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "expired-notice@example.com"))
        for sub in user.subscriptions:
            sub.expires_at = utcnow() - dt.timedelta(days=1)
        db.commit()

    body = client.get("/api/v1/servers", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["servers"] == []
    assert "подписка" in body["notice"].lower()


# --- доступ закрывается по-настоящему ----------------------------------------


def _paid_user(client, email: str):
    """Оплаченная учётка с пиром на узле — как у настоящего клиента."""
    from app.models import Provisioning, Server

    order = _order(client, email)
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        server = db.scalar(select(Server).where(Server.provisioning == Provisioning.SHARED))
        # Пир заводим руками: тестовый узел на общем ключе своих записей не
        # создаёт, а проверяем мы именно снятие пира.
        db.add(
            UserKey(
                user_id=user.id,
                server_id=server.id,
                config="[Interface]\n",
                public_key=f"key-{user.id}",
                address=f"10.0.0.{user.id % 250 + 2}/32",
            )
        )
        db.commit()
        return user.id, status["login"], status["password"]


def _live_keys(user_id: int) -> int:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        return sum(1 for k in user.keys if k.revoked_at is None)


def test_disable_tears_down_the_tunnel_immediately(client, auth):
    """
    «Отключить» обязано снять пир, а не только погасить сессию.

    Иначе в панели горит «отключён», а человек продолжает сидеть в
    интернете через наш узел: сессия приложения нужна только чтобы
    спросить список стран, а поднятый туннель живёт сам по себе.
    """
    uid, _, _ = _paid_user(client, "disable-me@example.com")
    assert _live_keys(uid) == 1

    r = client.post(f"/api/admin/users/{uid}/disable", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paused"
    assert _live_keys(uid) == 0, "пир остался на узле — туннель продолжит работать"

    # Включаем обратно: доступ возвращается, и вызывается выдача ключей.
    # Сам ключ здесь не появится — тестовый узел работает на общем ключе, а
    # для таких записей ensure_keys ничего не создаёт: конфиг лежит на самом
    # сервере. Переиздание пиров на узлах со своей генерацией проверяется
    # отдельно, в тестах ключей.
    r = client.post(f"/api/admin/users/{uid}/enable", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "offline"

    with SessionLocal() as db:
        assert db.get(User, uid).has_access()


def test_reissue_reuses_the_row_and_keeps_the_keypair(client, auth):
    """
    Повторная выдача обновляет существующую строку и не меняет ключ зря.

    Две беды в одном месте, обе стоили работающего доступа.

    Первая: на паре «пользователь + сервер» стоит уникальность, а выдача
    вставляла новую строку. Цикл «отключить → включить» падал с
    IntegrityError уже ПОСЛЕ добавления пира на узел — в базе ключа нет, в
    панели доступа нет, а пир на сервере работает и никем не отзывается.

    Вторая: возвращение доступа генерировало новую пару ключей, и конфиг,
    лежащий у человека в приложении, молча переставал работать.

    Проверяется на сервере со своей генерацией: у общего ключа записей нет.
    """
    from app.models import Provisioning, Server
    from app.services.keys import issue_key

    with SessionLocal() as db:
        server = Server(
            name="reissue-node",
            country="Тест",
            country_code="XX",
            host="10.20.30.9",
            provisioning=Provisioning.SSH,
            awg_template=(
                "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
                "[Peer]\nPublicKey = x\nEndpoint = 10.20.30.9:51820\n"
            ),
            ssh_host="10.20.30.9",
            ssh_user="root",
            ssh_password="x",
            is_active=False,  # в список приложению не попадёт
        )
        db.add(server)
        db.commit()
        server_id = server.id

    order = _order(client, "reissue@example.com")
    _deliver_webhook(client, order["id"])

    # SSH в тестах недопустим — заменяем заведение пира на узле заглушкой.
    import app.provisioning as prov

    added, removed = [], []
    real_add, real_remove = prov.add_peer_over_ssh, prov.remove_peer_over_ssh
    prov.add_peer_over_ssh = lambda s, pk, addr: added.append(pk)
    prov.remove_peer_over_ssh = lambda s, pk: removed.append(pk)

    try:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "reissue@example.com"))
            server = db.get(Server, server_id)

            first = issue_key(db, user, server)
            address, first_key = first.address, first.public_key

            # --- возвращение доступа: пара ключей обязана сохраниться ---
            #
            # Конфиг уже лежит у человека в приложении. Новая пара при
            # каждом «включить» молча превращала бы его в мусор: панель
            # показывает доступ, узел ждёт другой ключ, приложение стучится
            # старым и не получает ответа.
            first.revoked_at = utcnow_for_test()
            db.commit()

            second = issue_key(db, user, server)

            assert second.id == first.id, "вставлена вторая строка вместо обновления"
            assert second.revoked_at is None
            assert second.public_key == first_key, "ключ не должен меняться при возврате доступа"
            assert second.address == address
            assert added.count(first_key) == 2, "пир должен вернуться на узел тем же ключом"

            # --- осознанный перевыпуск: ключ обязан смениться ---
            third = issue_key(db, user, server, rotate=True)

            assert third.id == first.id, "перевыпуск тоже обновляет строку, а не вставляет"
            assert third.public_key != first_key, "при перевыпуске ключ должен быть новым"
            assert third.address == address, "адрес закреплён за строкой и не меняется"
            assert third.rx_bytes == 0 and third.tx_bytes == 0
            assert first_key in removed, "старый пир должен уйти с узла"

            rows = list(
                db.scalars(
                    select(UserKey).where(
                        UserKey.user_id == user.id, UserKey.server_id == server_id
                    )
                )
            )
            assert len(rows) == 1, f"строк на пару должно быть одна, а их {len(rows)}"
    finally:
        prov.add_peer_over_ssh, prov.remove_peer_over_ssh = real_add, real_remove


def utcnow_for_test():
    from app.models import utcnow

    return utcnow()


def test_block_tears_down_the_tunnel(client, auth):
    uid, _, _ = _paid_user(client, "block-me@example.com")
    assert _live_keys(uid) == 1

    r = client.post(f"/api/admin/users/{uid}/block", json={"reason": "проверка"}, headers=auth)
    assert r.json()["status"] == "blocked"
    assert _live_keys(uid) == 0


def test_traffic_limit_closes_access_automatically(client, auth):
    """Лимит выбран — пиры снимаются обходчиком, без участия человека."""
    from app.models import GB
    from app.services.traffic import enforce_access

    uid, _, _ = _paid_user(client, "traffic-out@example.com")

    client.post(
        f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": 1}, headers=auth
    )
    with SessionLocal() as db:
        user = db.get(User, uid)
        user.traffic_used_bytes = 2 * GB  # выбрал больше лимита
        db.commit()
        assert user.traffic_exhausted()

        closed = enforce_access(db)

    assert any("трафик исчерпан" in line for line in closed), closed
    assert _live_keys(uid) == 0


def test_expired_subscription_closes_access_automatically(client):
    """
    Подписка кончается сама, без единого запроса от кого-либо.

    Без регулярного обхода узлов человек продолжал бы пользоваться уже
    поднятым туннелем сколько угодно долго после окончания оплаты.
    """
    import datetime as dt

    from app.models import utcnow
    from app.services.traffic import enforce_access

    uid, _, _ = _paid_user(client, "expired-tunnel@example.com")
    assert _live_keys(uid) == 1

    with SessionLocal() as db:
        user = db.get(User, uid)
        for sub in user.subscriptions:
            sub.expires_at = utcnow() - dt.timedelta(days=1)
        db.commit()
        closed = enforce_access(db)

    assert any("подписка кончилась" in line for line in closed), closed
    assert _live_keys(uid) == 0


# --- что видит приложение ----------------------------------------------------


def test_app_sees_traffic_left_and_low_warning(client, auth):
    uid, login, password = _paid_user(client, "low-traffic@example.com")
    from app.models import GB

    client.post(f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": 10}, headers=auth)

    body = client.post("/api/v1/login", json={"login": login, "password": password}).json()
    s = body["subscription"]
    assert s["traffic_limit_bytes"] == 10 * GB
    assert s["traffic_left_bytes"] == 10 * GB
    assert s["traffic_low"] is False

    # Осталось меньше десятой части лимита.
    with SessionLocal() as db:
        db.get(User, uid).traffic_used_bytes = int(9.5 * GB)
        db.commit()

    body = client.post("/api/v1/login", json={"login": login, "password": password}).json()
    s = body["subscription"]
    assert s["traffic_low"] is True
    assert s["traffic_left_bytes"] == int(0.5 * GB)


def test_app_sees_days_left_and_renew_link_when_expiring(client):
    import datetime as dt

    from app.models import utcnow

    uid, login, password = _paid_user(client, "renew-soon@example.com")

    body = client.post("/api/v1/login", json={"login": login, "password": password}).json()
    assert body["subscription"]["days_left"] == 29
    assert body["subscription"]["expires_soon"] is False
    assert body["subscription"]["renew_url"] is None

    # Осталось два дня — приложению пора показать кнопку продления.
    with SessionLocal() as db:
        user = db.get(User, uid)
        for sub in user.subscriptions:
            sub.expires_at = utcnow() + dt.timedelta(days=2, hours=1)
        db.commit()

    body = client.post("/api/v1/login", json={"login": login, "password": password}).json()
    s = body["subscription"]
    assert s["days_left"] == 2
    assert s["expires_soon"] is True
    assert s["renew_url"].endswith("/account.html")


def test_panel_status_follows_vpn_handshake(client, auth):
    """
    «Онлайн» — это поднятый туннель, а не открытое приложение и не
    оплаченная подписка.
    """
    import datetime as dt

    from app.models import utcnow

    uid, _, _ = _paid_user(client, "handshake@example.com")

    row = client.get(f"/api/admin/users/{uid}", headers=auth).json()
    assert row["status"] == "offline", "без рукопожатия человек не онлайн"
    assert row["isOnline"] is False

    with SessionLocal() as db:
        user = db.get(User, uid)
        live = [k for k in user.keys if k.revoked_at is None][0]
        live.last_handshake_at = utcnow() - dt.timedelta(seconds=40)
        db.commit()

    row = client.get(f"/api/admin/users/{uid}", headers=auth).json()
    assert row["status"] == "online"
    assert row["isOnline"] is True

    # Рукопожатие протухло — человек отключился.
    with SessionLocal() as db:
        user = db.get(User, uid)
        live = [k for k in user.keys if k.revoked_at is None][0]
        live.last_handshake_at = utcnow() - dt.timedelta(minutes=20)
        db.commit()

    assert client.get(f"/api/admin/users/{uid}", headers=auth).json()["status"] == "offline"


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
