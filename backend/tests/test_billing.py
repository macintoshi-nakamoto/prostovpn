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
    utcnow,
)
from app.payments import mock as mock_provider
from app.services import billing_webhook


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
        plan = db.scalar(select(Plan).where(Plan.code == "basic"))
        plan.set_price(30_000)
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


def test_plans_come_from_database(client):
    r = client.get("/api/v1/plans")
    assert r.status_code == 200
    plans = {p["code"]: p for p in r.json()}

    with SessionLocal() as db:
        for plan in db.scalars(select(Plan).where(Plan.is_public.is_(True))):
            shown = plans[plan.code]
            assert shown["price_kopecks"] == plan.price_kopecks
            assert shown["duration_days"] == plan.period_days
            assert shown["device_limit"] == plan.device_limit
            assert shown["server_limit"] == plan.server_limit
            assert shown["traffic_limit_bytes"] == plan.traffic_limit_bytes

    assert plans["year"]["traffic_limit_bytes"] is None


def test_default_lineup_matches_the_announced_prices():
    from app.db import GB, DEFAULT_PLANS

    lineup = {row[0]: row for row in DEFAULT_PLANS}

    assert lineup["basic"][2] == 19_900
    assert lineup["3months"][2] == 49_900
    assert lineup["preyear"][2] == 89_900
    assert lineup["year"][2] == 149_900

    assert (lineup["basic"][3], lineup["3months"][3]) == (30, 90)
    assert (lineup["preyear"][3], lineup["year"][3]) == (180, 365)

    assert lineup["trial"][2] == 0
    assert lineup["trial"][3] == 2

    assert all(row[4] is None for row in DEFAULT_PLANS), "трафик где-то ограничен"

    assert (lineup["trial"][6], lineup["basic"][6]) == (5, 5)
    assert (lineup["3months"][6], lineup["preyear"][6], lineup["year"][6]) == (10, 10, 10)

    assert (lineup["daily"][2], lineup["daily"][3]) == (1_000, 1)


def test_trial_is_on_the_shelf_but_not_for_sale(client):
    plans = {p["code"]: p for p in client.get("/api/v1/plans").json()}

    trial = plans["trial"]
    assert trial["purchasable"] is False
    assert trial["duration_days"] == 2
    assert trial["traffic_limit_bytes"] is None
    assert plans["basic"]["purchasable"] is True

    r = client.post("/api/v1/orders", json={"plan_code": "trial", "email": "t@example.com"})
    assert r.status_code == 400, r.text


def _users_by_email(db, address: str) -> list:
    from app.crypto import blind_index
    from app.models import normalize_email

    return list(db.scalars(select(User).where(User.email_hash == blind_index(normalize_email(address)))))


def _user_by_email(db, address: str):
    found = _users_by_email(db, address)
    return found[0] if found else None


def test_twenty_deliveries_give_exactly_one_account(client):
    order = _order(client, "one@example.com")

    for attempt in range(1, 21):
        r = _deliver_webhook(client, order["id"], attempt=attempt)
        assert r.status_code == 200, r.text

    with SessionLocal() as db:
        users = _users_by_email(db, "one@example.com")
        assert len(users) == 1, f"учёток создано {len(users)}, ожидалась одна"

        subs = list(db.scalars(select(Subscription).where(Subscription.user_id == users[0].id)))
        assert len(subs) == 1, f"подписок создано {len(subs)}, ожидалась одна"

        jobs = list(db.scalars(select(DeliveryJob).where(DeliveryJob.user_id == users[0].id)))
        templates = sorted(job.template for job in jobs)
        assert templates == ["credentials", "receipt"], templates

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
    assert len(after["password"].split("-")) == 3
    assert after["expires_at"] is not None


def test_second_purchase_extends_instead_of_creating_second_user(client):
    first = _order(client, "renew@example.com")
    _deliver_webhook(client, first["id"])

    with SessionLocal() as db:
        user = _user_by_email(db, "renew@example.com")
        user_id, login = user.id, user.login
        password_hash = user.password_hash
        expires_first = user.active_subscription().expires_at

    second = _order(client, "renew@example.com")
    _deliver_webhook(client, second["id"])

    with SessionLocal() as db:
        users = _users_by_email(db, "renew@example.com")
        assert len(users) == 1, "повторная покупка завела второго пользователя"

        user = users[0]
        assert user.id == user_id and user.login == login
        assert user.password_hash == password_hash

        added = (user.active_subscription().expires_at - expires_first).days
        assert added == 30, f"продлили на {added} дней вместо 30"
        assert user.upcoming_subscriptions() == []
        live = [s for s in user.subscriptions if not s.is_cancelled and s.expires_at > utcnow()]
        assert len(live) == 1, "продление того же тарифа не должно заводить второй период"

    status = client.get(f"/api/v1/orders/{second['id']}/status").json()
    assert status["is_renewal"] is True
    assert status["password"] is None


def test_tampered_amount_is_rejected(client):
    order = _order(client, "fraud@example.com")

    with SessionLocal() as db:
        row = db.get(Order, order["id"])
        body = mock_provider.build_payload(row)

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
        assert _user_by_email(db, "fraud@example.com") is None
        failed = db.get(Order, order["id"])
        assert failed.status == OrderStatus.FAILED.value
        assert "заплачено меньше цены" in failed.failure_reason


def test_unsigned_webhook_is_forbidden(client):
    order = _order(client, "unsigned@example.com")
    with SessionLocal() as db:
        body = mock_provider.build_payload(db.get(Order, order["id"]))

    r = client.post("/api/v1/billing/webhook/mock", content=body)
    assert r.status_code == 403

    with SessionLocal() as db:
        assert _user_by_email(db, "unsigned@example.com") is None


def test_refund_cancels_subscription_and_revokes_peers(client):
    order = _order(client, "refund@example.com")
    _deliver_webhook(client, order["id"])

    with SessionLocal() as db:
        user = _user_by_email(db, "refund@example.com")
        assert user.has_access()

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
        user = _user_by_email(db, "refund@example.com")
        assert not user.has_access()
        assert all(sub.is_cancelled for sub in user.subscriptions)
        assert all(key.revoked_at is not None for key in user.keys)


def test_password_is_never_stored_or_logged_in_plaintext(client, caplog):
    caplog.set_level(logging.DEBUG)

    order = _order(client, "secret@example.com")
    _deliver_webhook(client, order["id"])
    password = client.get(f"/api/v1/orders/{order['id']}/status").json()["password"]
    assert password

    with SessionLocal() as db:
        user = _user_by_email(db, "secret@example.com")
        assert password not in user.password_hash
        assert user.password_hint is None
        assert user.password_enc and password not in user.password_enc

        from app.services import delivery

        delivery.run_once(db)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert password not in logged, "пароль попал в лог"


def test_email_is_encrypted_at_rest(client):
    address = "at-rest@example.com"
    order = _order(client, address)
    _deliver_webhook(client, order["id"])

    with SessionLocal() as db:
        user = _user_by_email(db, address)
        assert user is not None
        assert user.email is None
        assert user.contact != address
        assert user.email_enc and address not in user.email_enc
        import hashlib

        assert user.email_hash != hashlib.sha256(address.encode()).hexdigest()
        assert user.email_plain == address


def test_account_email_can_be_added_and_is_unique(client):
    r = client.post(
        "/api/v1/register",
        json={"login": "email-adder", "password": "pass-1234", "platform": "web"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/account", headers=headers).json()["email"] is None

    r = client.post("/api/v1/account/email", json={"email": "Cheques@Example.com"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "cheques@example.com"
    assert client.get("/api/v1/account", headers=headers).json()["email"] == "cheques@example.com"
    with SessionLocal() as db:
        user = _user_by_email(db, "cheques@example.com")
        assert user is not None and user.email is None and user.email_enc

    taken = _order(client, "occupied@example.com")
    _deliver_webhook(client, taken["id"])
    r = client.post("/api/v1/account/email", json={"email": "occupied@example.com"}, headers=headers)
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "email_taken"

    r = client.post("/api/v1/account/renew", json={"plan_code": "basic"}, headers=headers)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        assert db.get(Order, r.json()["id"]).email == "cheques@example.com"


def test_admin_reveal_writes_audit(client, auth):
    order = _order(client, "reveal@example.com")
    _deliver_webhook(client, order["id"])
    password = client.get(f"/api/v1/orders/{order['id']}/status").json()["password"]

    with SessionLocal() as db:
        user_id = _user_by_email(db, "reveal@example.com").id

    r = client.post(f"/api/admin/users/{user_id}/reveal", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["password"] == password

    log = client.get("/api/admin/audit", params={"action": "user.password_reveal"}, headers=auth)
    assert log.status_code == 200
    assert any(row["action"] == "user.password_reveal" for row in log.json())


def test_manual_fulfilment_when_webhook_never_arrived(client, auth):
    order = _order(client, "manual@example.com")

    r = client.post(f"/api/admin/orders/{order['id']}/fulfil", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    with SessionLocal() as db:
        assert _user_by_email(db, "manual@example.com") is not None

    _deliver_webhook(client, order["id"])
    with SessionLocal() as db:
        users = _users_by_email(db, "manual@example.com")
        assert len(users) == 1


def test_login_is_rate_limited(client):
    order = _order(client, "brute@example.com")
    _deliver_webhook(client, order["id"])
    login = client.get(f"/api/v1/orders/{order['id']}/status").json()["login"]

    codes = [
        client.post("/api/v1/login", json={"login": login, "password": "wrong"}).status_code
        for _ in range(7)
    ]
    assert 429 in codes, f"перебор не остановлен: {codes}"
    ghost = client.post("/api/v1/login", json={"login": "pv0000000", "password": "wrong"})
    assert ghost.status_code in (401, 429)


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
    assert body["devices"] == []
    assert "config" not in account.text and "PrivateKey" not in account.text


def test_browser_does_not_take_a_device_slot(client):
    order = _order(client, "slots@example.com")
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    def login(platform: str, device: str) -> str:
        r = client.post(
            "/api/v1/login",
            json={
                "login": status["login"],
                "password": status["password"],
                "platform": platform,
                "device_id": device,
                "device_name": device,
            },
        )
        assert r.status_code == 200, r.text
        return r.json()["token"]

    phone = login("android", "phone-1")
    for _ in range(4):
        login("web", f"browser-{_}")

    account = client.get("/api/v1/account", headers={"Authorization": f"Bearer {phone}"})
    assert account.status_code == 200, account.text
    devices = account.json()["devices"]
    assert [d["platform"] for d in devices] == ["android"]
    assert devices[0]["is_current"] is True


def test_telegram_bot_does_not_take_a_device_slot(client):
    order = _order(client, "bot-slot@example.com")
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    def login(payload: dict) -> str:
        r = client.post("/api/v1/login", json={**payload, "login": status["login"], "password": status["password"]})
        assert r.status_code == 200, r.text
        return r.json()["token"]

    phone = login({"platform": "android", "device_id": "phone-1", "device_name": "phone-1"})
    # Ровно так входит бот — см. bot/utils/panel.py: ни device_id, ни имени.
    login({"platform": "telegram", "app_version": "1.0.0"})

    account = client.get("/api/v1/account", headers={"Authorization": f"Bearer {phone}"})
    assert account.status_code == 200, account.text
    devices = account.json()["devices"]
    assert [d["platform"] for d in devices] == ["android"]


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

    first = client.get("/api/v1/account", headers={"Authorization": f"Bearer {tokens[0]}"})
    last = client.get("/api/v1/account", headers={"Authorization": f"Bearer {tokens[-1]}"})
    assert first.status_code == 401
    assert last.status_code == 200
    assert len(last.json()["devices"]) == 3


def test_order_rate_limit_mechanism(client):
    from app.services import ratelimit

    with SessionLocal() as db:
        key = "test:orders:203.0.113.7"
        allowed = sum(1 for _ in range(12) if ratelimit.hit(db, key, limit=10, window_minutes=60))
        assert allowed == 10, "ограничитель пропустил больше десяти заказов в час"
        assert ratelimit.hit(db, "test:orders:198.51.100.9", limit=10, window_minutes=60).allowed


def test_demo_servers_are_never_given_to_clients(client):
    from app.models import Provisioning, Server

    with SessionLocal() as db:
        db.add(
            Server(
                name="demo-broken",
                country="Демо",
                country_code="XX",
                host="203.0.113.15",
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
        user = _user_by_email(db, "expired-notice@example.com")
        for sub in user.subscriptions:
            sub.expires_at = utcnow() - dt.timedelta(days=1)
        db.commit()

    body = client.get("/api/v1/servers", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["servers"] == []
    assert "подписка" in body["notice"].lower()


def _paid_user(client, email: str):
    from app.models import Provisioning, Server

    order = _order(client, email)
    _deliver_webhook(client, order["id"])
    status = client.get(f"/api/v1/orders/{order['id']}/status").json()

    with SessionLocal() as db:
        from app.services.users import find_by_email

        user = find_by_email(db, email)
        server = db.scalar(select(Server).where(Server.provisioning == Provisioning.SHARED))
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
    uid, _, _ = _paid_user(client, "disable-me@example.com")
    assert _live_keys(uid) == 1

    r = client.post(f"/api/admin/users/{uid}/disable", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paused"
    assert _live_keys(uid) == 0, "пир остался на узле — туннель продолжит работать"

    r = client.post(f"/api/admin/users/{uid}/enable", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "offline"

    with SessionLocal() as db:
        assert db.get(User, uid).has_access()


def test_reissue_reuses_the_row_and_keeps_the_keypair(client, auth):
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
            is_active=False,
        )
        db.add(server)
        db.commit()
        server_id = server.id

    order = _order(client, "reissue@example.com")
    _deliver_webhook(client, order["id"])

    import app.provisioning as prov

    added, removed = [], []
    real_add, real_remove = prov.add_peer_over_ssh, prov.remove_peer_over_ssh
    prov.add_peer_over_ssh = lambda s, pk, addr, **_kw: added.append(pk)
    prov.remove_peer_over_ssh = lambda s, pk, **_kw: removed.append(pk)

    try:
        with SessionLocal() as db:
            user = _user_by_email(db, "reissue@example.com")
            server = db.get(Server, server_id)

            first = issue_key(db, user, server)
            address, first_key = first.address, first.public_key

            first.revoked_at = utcnow_for_test()
            db.commit()

            second = issue_key(db, user, server)

            assert second.id == first.id, "вставлена вторая строка вместо обновления"
            assert second.revoked_at is None
            assert second.public_key == first_key, "ключ не должен меняться при возврате доступа"
            assert second.address == address
            assert added.count(first_key) == 2, "пир должен вернуться на узел тем же ключом"

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
    from app.models import GB
    from app.services.traffic import enforce_access

    uid, _, _ = _paid_user(client, "traffic-out@example.com")

    client.post(
        f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": 1}, headers=auth
    )
    with SessionLocal() as db:
        user = db.get(User, uid)
        user.traffic_used_bytes = 2 * GB
        db.commit()
        assert user.traffic_exhausted()

        closed = enforce_access(db)

    assert any("трафик исчерпан" in line for line in closed), closed
    assert _live_keys(uid) == 0


def test_expired_subscription_closes_access_automatically(client):
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


def test_app_sees_traffic_left_and_low_warning(client, auth):
    uid, login, password = _paid_user(client, "low-traffic@example.com")
    from app.models import GB

    client.post(f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": 10}, headers=auth)

    body = client.post("/api/v1/login", json={"login": login, "password": password}).json()
    s = body["subscription"]
    assert s["traffic_limit_bytes"] == 10 * GB
    assert s["traffic_left_bytes"] == 10 * GB
    assert s["traffic_low"] is False

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

    # Дни для показа округляются вверх (access_days_left_display): только что
    # оплаченный месяц — это «30 дней», а не «29», как считало округление вниз.
    body = client.post("/api/v1/login", json={"login": login, "password": password}).json()
    assert body["subscription"]["days_left"] == 30
    assert body["subscription"]["expires_soon"] is False
    assert body["subscription"]["renew_url"] is None

    with SessionLocal() as db:
        user = db.get(User, uid)
        for sub in user.subscriptions:
            sub.expires_at = utcnow() + dt.timedelta(days=2, hours=1)
        db.commit()

    body = client.post("/api/v1/login", json={"login": login, "password": password}).json()
    s = body["subscription"]
    # Двое суток и час — это идущие третьи сутки, поэтому 3, а не 2.
    assert s["days_left"] == 3
    assert s["expires_soon"] is True
    assert s["renew_url"].endswith("/account")


def test_panel_status_follows_vpn_handshake(client, auth):
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
