"""
Проверка админского и клиентского API на живой базе.

Запуск: .venv/Scripts/python.exe -m pytest tests -q
Тесты работают на отдельной временной базе и не трогают рабочую panel.db.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

# Окружение задаётся в conftest.py: настройки кэшируются, и выставлять их
# в каждом модуле значит зависеть от порядка импорта.
from app.db import SessionLocal, init_db
from app.main import app
from app.models import GB, Provisioning, Server


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

    Адрес частный (RFC 1918), а не документационный. Документационные
    диапазоны панель теперь намеренно не отдаёт клиентам: узел с таким
    адресом — это всегда забытые демо-данные, и раздавать их живым людям
    хуже, чем не раздавать ничего. Режим SHARED, так что по адресу никто
    никуда не пойдёт.
    """
    with SessionLocal() as db:
        server = Server(
            name="test-nl",
            country="Нидерланды",
            country_en="Netherlands",
            city="Амстердам",
            country_code="NL",
            host="10.20.30.1",
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


def plan_price(client, auth, code: str) -> Decimal:
    """
    Цена тарифа из API, а не константой в тесте.

    Стартовые цены правятся — и правятся именно в базе, а не в коде. Тест,
    который знает их наизусть, ломается на каждой такой правке и ничего при
    этом не проверяет по существу.
    """
    plans = client.get("/api/admin/plans", headers=auth).json()
    return Decimal(next(p["price"] for p in plans if p["code"] == code))


def test_create_user_generates_credentials(client, auth):
    r = client.post(
        "/api/admin/users",
        json={"name": "Тестовый Клиент", "contact": "@test", "planCode": "3months"},
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
    assert user["plan"] == "3months"
    assert Decimal(user["price"]) == plan_price(client, auth, "3months")
    # Доступ есть, но к VPN человек ещё не подключался: статус отвечает на
    # вопрос «пользуется ли он сервисом сейчас», а не «оплачено ли».
    assert user["status"] == "offline"


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
    uid = client.post("/api/admin/users", json={"name": "Лимит", "planCode": "3months"}, headers=auth).json()["user"]["id"]

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


def test_personal_unlimited_beats_the_plan_limit(client, auth):
    """
    Безлимит человеку на тарифе С ЛИМИТОМ действительно снимает лимит.

    Прежний тест этого не ловил: он брал тариф без лимита, и «безлимит»
    выглядел сохранённым просто потому, что откатываться было не к чему.
    А на тарифе с лимитом администратор выбирал «Безлимит», в базу шло
    «своего лимита нет» — и лимит немедленно откатывался к тарифному.
    В панели это читалось как «не сохраняется», а человек оставался
    ограничен.
    """
    uid = client.post(
        "/api/admin/users", json={"name": "Личный безлимит", "planCode": "basic"}, headers=auth
    ).json()["user"]["id"]

    # На тарифе basic лимит есть — он и показывается, пока личного нет.
    plan_limited = client.get(f"/api/admin/users/{uid}", headers=auth).json()
    assert plan_limited["trafficLimitBytes"] == 250 * GB

    unlimited = client.post(
        f"/api/admin/users/{uid}/traffic-limit", json={"unlimited": True}, headers=auth
    ).json()
    assert unlimited["trafficLimitBytes"] is None, "личный безлимит откатился к тарифному лимиту"

    # И после перечитывания — тоже: панель открывают заново, а не смотрят
    # только на ответ сохранения.
    again = client.get(f"/api/admin/users/{uid}", headers=auth).json()
    assert again["trafficLimitBytes"] is None, "безлимит не пережил перечитывание карточки"

    # Расход больше тарифного лимита доступ не закрывает: безлимит же.
    from app.models import User

    with SessionLocal() as db:
        db.get(User, uid).traffic_used_bytes = 500 * GB
        db.commit()
    assert client.get(f"/api/admin/users/{uid}", headers=auth).json()["status"] != "traffic"

    # Обратно к тарифному лимиту: снимаем личный безлимит числом.
    back = client.post(
        f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": 10}, headers=auth
    ).json()
    assert back["trafficLimitBytes"] == 10 * GB, "личный лимит не встал обратно после безлимита"


def test_traffic_exhausted_blocks_access(client, auth):
    uid = client.post("/api/admin/users", json={"name": "Расход", "planCode": "3months"}, headers=auth).json()["user"]["id"]
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
    assert client.get(f"/api/admin/users/{uid}", headers=auth).json()["status"] == "offline"


def test_disable_block_unblock(client, auth):
    uid = client.post("/api/admin/users", json={"name": "Статусы", "planCode": "basic"}, headers=auth).json()["user"]["id"]

    assert client.post(f"/api/admin/users/{uid}/disable", headers=auth).json()["status"] == "paused"
    assert client.post(f"/api/admin/users/{uid}/enable", headers=auth).json()["status"] == "offline"

    blocked = client.post(
        f"/api/admin/users/{uid}/block", json={"reason": "проверка"}, headers=auth
    ).json()
    assert blocked["status"] == "blocked"
    assert "проверка" in blocked["blockedReason"]

    assert client.post(f"/api/admin/users/{uid}/unblock", headers=auth).json()["status"] == "offline"


def test_extend_registers_payment(client, auth):
    uid = client.post("/api/admin/users", json={"name": "Продление", "planCode": "basic"}, headers=auth).json()["user"]["id"]
    before = client.get(f"/api/admin/users/{uid}", headers=auth).json()

    after = client.post(
        f"/api/admin/users/{uid}/extend", json={"planCode": "3months"}, headers=auth
    ).json()

    # Продление — это и оплата: доступ и деньги не должны расходиться.
    assert len(after["payments"]) == len(before["payments"]) + 1
    assert Decimal(after["paidTotal"]) == Decimal(before["paidTotal"]) + plan_price(
        client, auth, "3months"
    )
    assert after["daysLeft"] >= before["daysLeft"]


def test_blocked_user_cannot_log_in(client, auth, shared_server):
    created = client.post(
        "/api/admin/users", json={"name": "Бан", "planCode": "3months"}, headers=auth
    ).json()
    login, password = created["user"]["login"], created["password"]

    ok = client.post("/api/v1/login", json={"login": login, "password": password})
    assert ok.status_code == 200, ok.text

    client.post(f"/api/admin/users/{created['user']['id']}/block", json={}, headers=auth)
    denied = client.post("/api/v1/login", json={"login": login, "password": password})
    assert denied.status_code == 401


def test_client_login_returns_servers_without_ip_or_keys(client, auth, shared_server):
    created = client.post(
        "/api/admin/users", json={"name": "Клиент Приложения", "planCode": "3months"}, headers=auth
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
        "/api/admin/users", json={"name": "Ушедший", "planCode": "3months"}, headers=auth
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

# Контрольная сумма установщика. В тестах про сравнение версий важно только
# то, что она есть: без неё панель не публикует версию — приложение такое
# обновление всё равно откажется ставить.
SHA256 = "a" * 64


def test_release_publish_and_check(client, auth):
    """Приложение спрашивает версию без токена — и на экране входа тоже."""
    r = client.post(
        "/api/admin/releases",
        json={
            "platform": "windows",
            "version": "2.2.0",
            "url": "https://example.com/ProstoVPN-2.2.0.msi",
            "changelog": "Вход по логину и паролю",
            "sha256": SHA256,
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
        json={
            "platform": "linux",
            "version": "2.10.0",
            "url": "https://example.com/a.AppImage",
            "sha256": SHA256,
        },
        headers=auth,
    )
    client.post(
        "/api/admin/releases",
        json={
            "platform": "linux",
            "version": "2.9.0",
            "url": "https://example.com/b.AppImage",
            "sha256": SHA256,
        },
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
            "sha256": SHA256,
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
            json={"platform": "macos", "version": "1.0.0", "url": url, "sha256": SHA256},
            headers=auth,
        )
    rows = [r for r in client.get("/api/admin/releases", headers=auth).json() if r["platform"] == "macos"]
    assert len(rows) == 1
    assert rows[0]["url"].endswith("v2.msi")


def test_release_without_checksum_is_not_published(client, auth):
    """
    Версия без контрольной суммы — это неработающая кнопка «Обновить».

    Приложение не ставит установщик, суммы которого панель не назвала: он
    запускается с правами администратора, и проверить его больше нечем.
    Пока сумму вписывали руками, её не вписывал никто, и обновление падало
    ошибкой у всех сразу — поэтому панель либо считает её сама, либо
    отказывает в публикации и говорит почему.
    """
    # Порт 9 отбрасывает соединение сразу: до сети тест не идёт.
    r = client.post(
        "/api/admin/releases",
        json={"platform": "windows", "version": "9.9.9", "url": "http://127.0.0.1:9/app.msi"},
        headers=auth,
    )
    assert r.status_code == 400, r.text
    assert "сумм" in r.json()["detail"]

    # Черновик — можно: его приложениям не предлагают, а файла может ещё
    # и не быть.
    draft = client.post(
        "/api/admin/releases",
        json={
            "platform": "windows",
            "version": "9.9.9",
            "url": "http://127.0.0.1:9/app.msi",
            "isActive": False,
        },
        headers=auth,
    )
    assert draft.status_code == 201, draft.text


def test_release_rejects_malformed_checksum(client, auth):
    r = client.post(
        "/api/admin/releases",
        json={
            "platform": "windows",
            "version": "9.9.8",
            "url": "https://example.com/app.msi",
            "sha256": "не-шестнадцатеричная",
        },
        headers=auth,
    )
    assert r.status_code == 400, r.text


def test_saving_server_does_not_wipe_template_and_ssh(client, auth, shared_server):
    """
    Сохранение узла ради переименования не должно ломать выдачу доступа.

    Шаблон конфига, общий ключ, пароль и ключ SSH наружу не отдаются — иначе
    они разъезжались бы в каждом ответе со списком серверов. Форма поэтому
    присылает по ним пустоту, и присваивание без проверки стирало бы ровно
    то, на чём держится доступ: узел оставался включённым, зелёным и
    неработающим.
    """
    created = client.post(
        "/api/admin/servers",
        json={
            "name": "wipe-test",
            "country": "Тест",
            "host": "10.20.30.50",
            "provisioning": "ssh",
            "awgTemplate": "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n",
            "sshHost": "10.20.30.50",
            "sshUser": "root",
            "sshPassword": "секрет",
            "isActive": False,
            "issueKeys": False,
        },
        headers=auth,
    )
    assert created.status_code == 201, created.text
    server = created.json()["server"]
    assert server["hasTemplate"] is True
    # Адрес и учётка SSH обязаны приходить обратно: без них форма подставит
    # свои значения по умолчанию и уведёт панель на чужую машину.
    assert server["sshHost"] == "10.20.30.50"
    assert server["sshUser"] == "root"
    assert server["hasSshSecret"] is True

    # Так делает форма при простом переименовании: секретов не присылает.
    renamed = client.put(
        f"/api/admin/servers/{server['id']}",
        json={
            "name": "wipe-test-renamed",
            "country": "Тест",
            "host": "10.20.30.50",
            "provisioning": "ssh",
            "awgTemplate": "",
            "sharedConfig": "",
            "sshHost": "10.20.30.50",
            "sshUser": "root",
            "sshPassword": "",
            "sshKey": "",
            "isActive": False,
        },
        headers=auth,
    )
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["name"] == "wipe-test-renamed"
    assert body["hasTemplate"] is True, "шаблон конфига стёрт сохранением"
    assert body["hasSshSecret"] is True, "доступ по SSH стёрт сохранением"
    assert body["canServe"] is False  # узел выключен, но пригоден


def test_server_without_config_source_is_rejected(client, auth):
    """Узел, которому нечего выдать клиенту, заводить нельзя."""
    r = client.post(
        "/api/admin/servers",
        json={
            "name": "no-template",
            "host": "10.20.30.51",
            "provisioning": "ssh",
            "isActive": False,
            "issueKeys": False,
        },
        headers=auth,
    )
    assert r.status_code == 400
    assert "шаблон" in r.json()["detail"]


# --- регистрация с сайта ------------------------------------------------------


def test_register_creates_account_and_signs_in(client):
    """
    Регистрация сразу пускает внутрь.

    Отдельный вход после неё — лишний ввод тех же логина и пароля, поэтому
    ответ здесь такой же, как у /login: с токеном и подпиской.
    """
    r = client.post(
        "/api/v1/register",
        json={"login": "novichok", "password": "dovolno-dlinnyi", "email": "n@example.com"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"]
    assert body["account"]["login"] == "novichok"
    # Пробный тариф выдаётся сразу, иначе заходить некуда.
    assert body["subscription"]["active"] is True

    # Токен настоящий: с ним работают обычные маршруты приложения.
    me = client.get("/api/v1/servers", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200


def test_register_rejects_taken_login(client):
    payload = {"login": "zanyato", "password": "dovolno-dlinnyi"}
    assert client.post("/api/v1/register", json=payload).status_code == 201
    second = client.post("/api/v1/register", json=payload)
    assert second.status_code == 400
    # Код причины нужен приложению: текст панели русский, а интерфейс бывает
    # английским.
    assert second.headers.get("X-Error-Code") == "login_taken"


def test_register_rejects_short_password(client):
    r = client.post("/api/v1/register", json={"login": "korotysh", "password": "1234567"})
    assert r.status_code == 422


def test_register_rejects_login_with_spaces(client):
    r = client.post("/api/v1/register", json={"login": "два слова", "password": "dovolno-dlinnyi"})
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "login_invalid"


def test_register_is_rate_limited_per_address(client):
    """
    Бесплатный доступ без ограничения раздаётся одним скриптом в сто рук.

    Лимит наполняем сами, а не гоняем регистрацию по кругу: боевое число
    большое, а в прогоне оно поднято ещё выше, чтобы не мешать остальным
    тестам. Проверяем здесь именно то, что маршрут смотрит на ограничитель.
    """
    from app import services
    from app.config import settings
    from app.db import SessionLocal

    config = settings()
    # Адрес подставляем заголовком, как это делает nginx: у TestClient хост
    # «testclient», и проверку формата в client_ip он не проходит — все
    # запросы прогона иначе считались бы под одним ключом «unknown».
    address = "203.0.113.77"
    key = f"signup:{address}"
    with SessionLocal() as db:
        for _ in range(config.signup_max_per_ip):
            services.ratelimit.hit(
                db,
                key,
                limit=config.signup_max_per_ip,
                window_minutes=config.signup_window_minutes,
                lock_minutes=config.signup_window_minutes,
            )

    r = client.post(
        "/api/v1/register",
        json={"login": "perebor", "password": "dovolno-dlinnyi"},
        headers={"X-Forwarded-For": address},
    )
    assert r.status_code == 429, r.text
    assert r.headers.get("X-Error-Code") == "throttled"
    # Приложению нужно знать, когда можно повторить, а не только что нельзя.
    assert r.headers.get("Retry-After")


def test_register_recovers_from_prior_login_lockout(client):
    """
    Регистрация не падает 500-й, если логин был заперт неудачными входами.

    Человек несколько раз пробует войти под логином, которого ещё нет
    (думает, что аккаунт есть), — и запирает бакет входа. Потом жмёт
    «Зарегистрироваться». Раньше authenticate внутри register упирался в
    замок УЖЕ после create_user: 500, учётка заведена, токена нет, а повтор
    жалуется «логин занят». Теперь свой только что созданный логин
    отпирается — регистрация проходит и сразу пускает внутрь.
    """
    from app.config import settings

    login = "byl-zablokirovan"
    config = settings()
    address = "203.0.113.90"

    # Запираем вход этим логином: больше лимита неудачных попыток.
    for _ in range(config.login_max_attempts + 1):
        client.post(
            "/api/v1/login",
            json={"login": login, "password": "nevernyi"},
            headers={"X-Forwarded-For": address},
        )

    # Убеждаемся, что вход действительно заперт.
    throttled = client.post(
        "/api/v1/login",
        json={"login": login, "password": "nevernyi"},
        headers={"X-Forwarded-For": address},
    )
    assert throttled.status_code == 429, throttled.text

    # А регистрация тем же логином с того же адреса — проходит и даёт токен.
    r = client.post(
        "/api/v1/register",
        json={"login": login, "password": "dovolno-dlinnyi"},
        headers={"X-Forwarded-For": address},
    )
    assert r.status_code == 201, r.text
    assert r.json()["token"]


# --- трафик: предупреждение и отключение --------------------------------------


def test_traffic_low_threshold_scales_with_the_limit(client, auth, shared_server):
    """
    Порог предупреждения подстраивается под лимит: пятая часть, но не
    больше пяти гигабайт.

    Оба перекоса — настоящие. Доля без планки на 250 ГБ пугала за 25 ГБ до
    конца — больше, чем весь пробный тариф. Абсолютные пять гигабайт при
    лимите в один горели с первой секунды: «осталось мало: 1020 МБ» у
    человека, израсходовавшего четыре мегабайта.
    """
    from app.models import GB, User

    created = client.post(
        "/api/admin/users", json={"name": "Трафик Порог", "planCode": "3months"}, headers=auth
    ).json()
    uid, login, password = created["user"]["id"], created["user"]["login"], created["password"]

    def subscription() -> dict:
        r = client.post("/api/v1/login", json={"login": login, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["subscription"]

    def set_state(limit_gb: int, used_bytes: int) -> None:
        client.post(f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": limit_gb}, headers=auth)
        with SessionLocal() as db:
            db.get(User, uid).traffic_used_bytes = used_bytes
            db.commit()

    # Большой тариф: планка в пять гигабайт. За 20 ГБ до конца — рано.
    set_state(250, 230 * GB)
    assert subscription()["traffic_low"] is False

    # Осталось 4 ГБ — пора; и человеку есть куда нажать.
    set_state(250, 246 * GB)
    low = subscription()
    assert low["traffic_low"] is True
    assert low["traffic_left_bytes"] == 4 * GB
    assert low["renew_url"]

    # Маленький лимит: гигабайт. Израсходованы четыре мегабайта — свежая
    # учётка не должна встречать человека словами «трафика осталось мало».
    set_state(1, 4 * 1024 * 1024)
    assert subscription()["traffic_low"] is False

    # А вот когда осталась пятая часть (200 МБ) — пора.
    set_state(1, GB - 200 * 1024 * 1024)
    assert subscription()["traffic_low"] is True


def test_exhausted_traffic_revokes_keys_and_closes_access(client, auth, shared_server):
    """
    Выбранный трафик отключает по-настоящему: пир уходит с узла.

    Без этого человек продолжал бы пользоваться уже поднятым туннелем: сам
    туннель живёт на сервере и о лимите ничего не знает, а приложение к нему
    больше не обращается.

    Ключ заводим записью в базу, а не выдачей. Пиров по людям заводит только
    режим SSH — он ходит на живой узел, которого в тестах нет; а снимает их
    один и тот же `revoke_key` независимо от режима. Так проверяется именно
    решение «доступа нет — ключ долой», а не доступность чужой машины.
    """
    from app.models import GB, User, UserKey
    from app.services.traffic import enforce_access

    created = client.post(
        "/api/admin/users", json={"name": "Трафик Конец", "planCode": "3months"}, headers=auth
    ).json()
    uid, login, password = created["user"]["id"], created["user"]["login"], created["password"]
    client.post(f"/api/admin/users/{uid}/traffic-limit", json={"limitGb": 10}, headers=auth)

    # Серверы приходят: доступ есть.
    assert client.post("/api/v1/login", json={"login": login, "password": password}).json()["servers"]

    with SessionLocal() as db:
        db.add(
            UserKey(
                user_id=uid,
                server_id=shared_server,
                public_key="peer-of-exhausted-user",
                config="[Interface]\nAddress = 10.0.0.9/32\n",
            )
        )
        db.get(User, uid).traffic_used_bytes = 11 * GB
        db.commit()

    with SessionLocal() as db:
        closed = enforce_access(db)
    assert any(created["user"]["publicId"] in line for line in closed), closed
    assert any("трафик" in line for line in closed), closed

    with SessionLocal() as db:
        user = db.get(User, uid)
        assert user.has_access() is False
        # Живых ключей не осталось — на узле пира больше нет.
        assert [k for k in user.keys if k.revoked_at is None] == []

    # И список серверов пуст: приложению отдавать нечего.
    after = client.post("/api/v1/login", json={"login": login, "password": password})
    assert after.json()["servers"] == []
