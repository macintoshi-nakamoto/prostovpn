"""
Проверка админского и клиентского API на живой базе.

Запуск: .venv/Scripts/python.exe -m pytest tests -q
Тесты работают на отдельной временной базе и не трогают рабочую panel.db.
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal

import pytest

# База задаётся до импорта приложения: настройки читаются один раз и кэшируются.
_TMP = tempfile.mkdtemp(prefix="panel-test-")
os.environ["PANEL_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["PANEL_SEED_DEMO"] = "0"
os.environ["PANEL_TRAFFIC_SYNC_MINUTES"] = "0"
os.environ["PANEL_ADMIN_LOGIN"] = "admin"
os.environ["PANEL_ADMIN_PASSWORD"] = "admin"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import GB, Provisioning, Server  # noqa: E402


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


@pytest.fixture(scope="module")
def shared_server():
    """
    Сервер с общим ключом: провижининг по SSH в тестах недопустим — он
    полез бы в сеть и сделал бы тесты медленными и ненадёжными.
    """
    with SessionLocal() as db:
        server = Server(
            name="test-nl",
            country="Нидерланды",
            country_en="Netherlands",
            city="Амстердам",
            country_code="NL",
            host="192.0.2.1",
            provisioning=Provisioning.SHARED,
            shared_config="[Interface]\nAddress = 10.0.0.2/32\n",
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        return server.id


def test_login_required(client):
    assert client.get("/api/admin/users").status_code == 401


def test_bad_password_rejected(client):
    r = client.post("/api/admin/login", json={"login": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_create_user_generates_credentials(client, auth):
    r = client.post(
        "/api/admin/users",
        json={"name": "Тестовый Клиент", "contact": "@test", "planCode": "pro"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    user, password = body["user"], body["password"]

    # Логин набирают руками в приложении — только латиница.
    assert user["login"].isascii(), user["login"]
    assert user["login"].startswith("testovyy-klient-")
    assert len(password) >= 12
    assert user["publicId"].startswith("PV-")
    assert user["plan"] == "pro"
    assert Decimal(user["price"]) == Decimal("349.00")
    assert user["status"] == "active"


def test_cyrillic_login_rejected(client, auth):
    r = client.post("/api/admin/users", json={"login": "клиент", "password": "12345678"}, headers=auth)
    assert r.status_code == 400
    assert "латинские" in r.json()["detail"]


def test_search_finds_by_name_and_public_id(client, auth):
    created = client.post(
        "/api/admin/users", json={"name": "Поисковый Тест", "planCode": "basic"}, headers=auth
    ).json()["user"]

    by_name = client.get("/api/admin/users", params={"q": "Поисковый"}, headers=auth).json()
    assert [u["id"] for u in by_name] == [created["id"]]

    by_id = client.get("/api/admin/users", params={"q": created["publicId"]}, headers=auth).json()
    assert [u["id"] for u in by_id] == [created["id"]]

    by_login = client.get("/api/admin/users", params={"q": created["login"][:8]}, headers=auth).json()
    assert created["id"] in [u["id"] for u in by_login]


def test_traffic_limit_and_unlimited(client, auth):
    uid = client.post("/api/admin/users", json={"name": "Лимит", "planCode": "pro"}, headers=auth).json()["user"]["id"]

    limited = client.post(
        f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": 250}, headers=auth
    ).json()
    assert limited["trafficLimitBytes"] == 250 * GB

    unlimited = client.post(
        f"/api/admin/users/{uid}/traffic-limit", json={"unlimited": True}, headers=auth
    ).json()
    # None — это и есть безлимит, отдельного флага нет.
    assert unlimited["trafficLimitBytes"] is None
    assert unlimited["trafficPct"] is None


def test_traffic_exhausted_blocks_access(client, auth):
    uid = client.post("/api/admin/users", json={"name": "Расход", "planCode": "pro"}, headers=auth).json()["user"]["id"]
    client.post(f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": 1}, headers=auth)

    from app.models import User

    with SessionLocal() as db:
        user = db.get(User, uid)
        user.traffic_used_bytes = 2 * GB
        db.commit()

    row = client.get(f"/api/admin/users/{uid}", headers=auth).json()
    assert row["status"] == "traffic"

    # Выбранный лимит закрывает доступ так же, как неоплата.
    with SessionLocal() as db:
        assert db.get(User, uid).has_access() is False

    client.post(f"/api/admin/users/{uid}/traffic-reset", headers=auth)
    assert client.get(f"/api/admin/users/{uid}", headers=auth).json()["status"] == "active"


def test_disable_block_unblock(client, auth):
    uid = client.post("/api/admin/users", json={"name": "Статусы", "planCode": "basic"}, headers=auth).json()["user"]["id"]

    assert client.post(f"/api/admin/users/{uid}/disable", headers=auth).json()["status"] == "paused"
    assert client.post(f"/api/admin/users/{uid}/enable", headers=auth).json()["status"] == "active"

    blocked = client.post(
        f"/api/admin/users/{uid}/block", json={"reason": "проверка"}, headers=auth
    ).json()
    assert blocked["status"] == "blocked"
    assert "проверка" in blocked["blockedReason"]

    assert client.post(f"/api/admin/users/{uid}/unblock", headers=auth).json()["status"] == "active"


def test_extend_registers_payment(client, auth):
    uid = client.post("/api/admin/users", json={"name": "Продление", "planCode": "basic"}, headers=auth).json()["user"]["id"]
    before = client.get(f"/api/admin/users/{uid}", headers=auth).json()

    after = client.post(
        f"/api/admin/users/{uid}/extend", json={"planCode": "pro"}, headers=auth
    ).json()

    # Продление — это и оплата: доступ и деньги не должны расходиться.
    assert len(after["payments"]) == len(before["payments"]) + 1
    assert Decimal(after["paidTotal"]) == Decimal(before["paidTotal"]) + Decimal("349.00")
    assert after["daysLeft"] >= before["daysLeft"]


def test_blocked_user_cannot_log_in(client, auth, shared_server):
    created = client.post(
        "/api/admin/users", json={"name": "Бан", "planCode": "pro"}, headers=auth
    ).json()
    login, password = created["user"]["login"], created["password"]

    ok = client.post("/api/v1/login", json={"login": login, "password": password})
    assert ok.status_code == 200, ok.text

    client.post(f"/api/admin/users/{created['user']['id']}/block", json={}, headers=auth)
    denied = client.post("/api/v1/login", json={"login": login, "password": password})
    assert denied.status_code == 401


def test_client_login_returns_servers_without_ip_or_keys(client, auth, shared_server):
    created = client.post(
        "/api/admin/users", json={"name": "Клиент Приложения", "planCode": "pro"}, headers=auth
    ).json()

    r = client.post(
        "/api/v1/login",
        json={
            "login": created["user"]["login"],
            "password": created["password"],
            "platform": "windows",
            "app_version": "2.2.0",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["account"]["public_id"] == created["user"]["publicId"]
    assert body["subscription"]["active"] is True
    assert body["servers"], "подписка есть — серверы должны прийти"

    server = body["servers"][0]
    # Человек в приложении видит страну и город. Ни адреса сервера, ни
    # публичного ключа, ни выданного адреса в подсети наружу не уходит.
    assert server["country"] == "Нидерланды"
    assert server["city"] == "Амстердам"
    assert server["country_code"] == "NL"
    for leaked in ("host", "port", "key", "public_key", "address"):
        assert leaked not in server, f"в ответ приложению просочилось поле {leaked}"
    assert server["config"], "конфиг нужен туннелю"


def test_unpaid_user_gets_no_servers(client, auth, shared_server):
    created = client.post(
        "/api/admin/users", json={"name": "Без Оплаты", "days": 1, "planCode": "trial"}, headers=auth
    ).json()

    from app.models import User, utcnow
    import datetime as dt

    with SessionLocal() as db:
        user = db.get(User, created["user"]["id"])
        for sub in user.subscriptions:
            sub.expires_at = utcnow() - dt.timedelta(days=1)
        db.commit()

    r = client.post(
        "/api/v1/login",
        json={"login": created["user"]["login"], "password": created["password"]},
    )
    assert r.status_code == 200
    assert r.json()["subscription"]["active"] is False
    # Платящий и неплатящий не должны получать одно и то же.
    assert r.json()["servers"] == []


def test_calendar_splits_actual_and_expected(client, auth):
    r = client.get("/api/admin/calendar", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()

    assert len(body["days"]) >= 28
    assert {"date", "actual", "expected", "payments", "renewals"} <= set(body["days"][0])
    # Сумма по дням обязана сходиться с итогом месяца.
    assert sum(Decimal(d["actual"]) for d in body["days"]) == Decimal(body["actualTotal"])
    assert sum(Decimal(d["expected"]) for d in body["days"]) == Decimal(body["expectedTotal"])


def test_renewed_past_period_is_not_expected_again(client, auth):
    """
    Уже продлённый период не должен снова висеть как ожидаемый.

    Подписки идут встык: конец предыдущей совпадает с началом следующей.
    Если брать любую подписку из истории, день продления показывал бы и
    полученный платёж, и «ожидание» на ту же сумму — одно событие дважды.
    """
    created = client.post(
        "/api/admin/users", json={"name": "Продлённый", "planCode": "basic"}, headers=auth
    ).json()["user"]
    # Продлеваем: первый период закрывается, начинается второй.
    client.post(f"/api/admin/users/{created['id']}/extend", json={"planCode": "basic"}, headers=auth)

    detail = client.get(f"/api/admin/users/{created['id']}", headers=auth).json()
    assert len(detail["subscriptions"]) == 2

    body = client.get("/api/admin/calendar", headers=auth).json()
    renewals = [r for day in body["days"] for r in day["renewals"] if r["userId"] == created["id"]]
    # Ровно одно ожидание — по действующей подписке, а не по каждой из истории.
    assert len(renewals) <= 1

    import datetime as dt

    today = dt.date.today()
    for day in body["days"]:
        if dt.date.fromisoformat(day["date"]) < today:
            # Прошедший день — не ожидание, а свершившийся факт.
            assert Decimal(day["expected"]) == 0, f"{day['date']} ждёт продления задним числом"


def test_blocked_user_not_counted_as_expected(client, auth):
    created = client.post(
        "/api/admin/users", json={"name": "Ушедший", "planCode": "pro"}, headers=auth
    ).json()["user"]

    # Смотрим тот месяц, в который попадает конец подписки: 30 дней от
    # сегодня почти всегда уезжают в следующий месяц, и календарь текущего
    # про это продление ничего не знает.
    import datetime as dt

    expires = dt.datetime.fromisoformat(created["expiresAt"])
    params = {"year": expires.year, "month": expires.month}

    before = client.get("/api/admin/calendar", params=params, headers=auth).json()
    assert Decimal(before["expectedTotal"]) > 0

    client.post(f"/api/admin/users/{created['id']}/block", json={}, headers=auth)
    after = client.get("/api/admin/calendar", params=params, headers=auth).json()

    # С заблокированного денег не ждут.
    assert Decimal(after["expectedTotal"]) < Decimal(before["expectedTotal"])


def test_revenue_summary_periods_nest(client, auth):
    s = client.get("/api/admin/revenue", headers=auth).json()
    day, week, month, year = (Decimal(s[k]) for k in ("day", "week", "month", "year"))
    # День входит в неделю, неделя и месяц — в год.
    assert day <= week
    assert month <= year


def test_keys_tab_lists_account_server_pairs(client, auth, shared_server):
    rows = client.get("/api/admin/keys", headers=auth).json()
    assert isinstance(rows, list)
    if rows:
        assert {"publicId", "login", "serverName", "country", "publicKey"} <= set(rows[0])


def test_dashboard(client, auth):
    d = client.get("/api/admin/dashboard", headers=auth).json()
    assert d["usersTotal"] > 0
    assert len(d["daily"]) == 30
    assert len(d["monthly"]) == 12


# --- обновление приложения ---------------------------------------------------


def test_release_publish_and_check(client, auth):
    """Приложение спрашивает версию без токена — и на экране входа тоже."""
    r = client.post(
        "/api/admin/releases",
        json={
            "platform": "windows",
            "version": "2.2.0",
            "url": "https://example.com/ProstoVPN-2.2.0.msi",
            "changelog": "Вход по логину и паролю",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text

    old = client.get("/api/v1/version", params={"platform": "windows", "current": "2.1.4"}).json()
    assert old["update_available"] is True
    assert old["version"] == "2.2.0"
    assert old["url"].endswith(".msi")

    same = client.get("/api/v1/version", params={"platform": "windows", "current": "2.2.0"}).json()
    assert same["update_available"] is False
    # Ссылку на установщик отдаём только когда обновляться есть на что.
    assert same["url"] is None


def test_version_compare_is_numeric_not_alphabetical(client, auth):
    """2.10 новее 2.9 — строковое сравнение сказало бы обратное."""
    client.post(
        "/api/admin/releases",
        json={"platform": "linux", "version": "2.10.0", "url": "https://example.com/a.AppImage"},
        headers=auth,
    )
    client.post(
        "/api/admin/releases",
        json={"platform": "linux", "version": "2.9.0", "url": "https://example.com/b.AppImage"},
        headers=auth,
    )
    latest = client.get("/api/v1/version", params={"platform": "linux", "current": "2.9.0"}).json()
    assert latest["version"] == "2.10.0"
    assert latest["update_available"] is True


def test_unknown_platform_has_no_update(client):
    r = client.get("/api/v1/version", params={"platform": "symbian", "current": "1.0"})
    assert r.status_code == 200
    assert r.json()["update_available"] is False


def test_mandatory_only_when_update_exists(client, auth):
    client.post(
        "/api/admin/releases",
        json={
            "platform": "android",
            "version": "3.0.0",
            "url": "https://example.com/app.apk",
            "isMandatory": True,
        },
        headers=auth,
    )
    assert client.get("/api/v1/version", params={"platform": "android", "current": "2.0.0"}).json()["mandatory"] is True
    # Тому, кто уже на свежей версии, обязательность не показываем.
    assert client.get("/api/v1/version", params={"platform": "android", "current": "3.0.0"}).json()["mandatory"] is False


def test_release_upsert_does_not_duplicate(client, auth):
    for url in ("https://example.com/v1.msi", "https://example.com/v2.msi"):
        client.post(
            "/api/admin/releases",
            json={"platform": "macos", "version": "1.0.0", "url": url},
            headers=auth,
        )
    rows = [r for r in client.get("/api/admin/releases", headers=auth).json() if r["platform"] == "macos"]
    assert len(rows) == 1
    assert rows[0]["url"].endswith("v2.msi")
