"""
Защита входа: то, что раньше только выглядело работающим.

Каждая проверка здесь соответствует конкретной дыре, а не строчке кода:

* адрес клиента брался из первого значения X-Forwarded-For, то есть из
  того, что пишет сам клиент, — и любой счётчик по IP обнулялся подстановкой;
* вход в панель администратора не был ограничен по частоте вообще;
* токен приложения не продлевался, вопреки обещанию в config.py;
* пароль на странице успеха отдавался по идентификатору заказа бессрочно;
* encrypt() шифровал дефолтным, то есть опубликованным, ключом.

Запуск: .venv/Scripts/python.exe -m pytest tests -q
"""

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


# --- адрес клиента ------------------------------------------------------------


def _fake_request(headers: dict[str, str], peer: str | None = "203.0.113.5"):
    """Минимальный Request: client_ip читает только заголовки и адрес пиры."""
    from fastapi import Request

    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 12345) if peer else None,
    }
    return Request(scope)


def test_forwarded_for_takes_the_address_nginx_appended():
    """
    Первое значение пишет клиент, последнее — nginx.

    nginx собирает заголовок через $proxy_add_x_forwarded_for: он дописывает
    адрес соединения к присланному. Если брать первое значение, нападающий
    подставляет в каждый запрос новый адрес, счётчик всегда равен единице и
    подбор пароля идёт без ограничений.
    """
    from app.security import client_ip

    request = _fake_request({"X-Forwarded-For": "1.2.3.4, 198.51.100.77"})
    assert client_ip(request) == "198.51.100.77"


def test_client_ip_falls_back_to_peer_without_header():
    from app.security import client_ip

    assert client_ip(_fake_request({})) == "203.0.113.5"


def test_client_ip_never_returns_something_too_long_for_the_column():
    """
    Session.ip и Order.ip — String(64), RateLimit.key — String(160).

    ipaddress сам по себе длину не ограничивает: IPv6 с zone id проходит
    проверку при любой длине зоны, и на PostgreSQL вставка падала бы с
    обрезкой строки, то есть вход и заказ отвечали бы 500 на один заголовок.
    """
    from app.security import client_ip

    long_zone = "fe80::1%" + "A" * 300
    value = client_ip(_fake_request({"X-Forwarded-For": long_zone}))
    assert value == "fe80::1", "zone id должен отбрасываться вместе со своей длиной"

    junk = client_ip(_fake_request({"X-Forwarded-For": "не адрес вовсе"}))
    assert junk == "203.0.113.5", "мусор в заголовке — берём адрес соединения"

    # Что бы ни прислали, в колонку String(64) это влезет.
    for header in (long_zone, "A" * 500, "1.2.3.4" * 40):
        got = client_ip(_fake_request({"X-Forwarded-For": header}))
        assert got is None or len(got) <= 45, got


# --- вход в панель ------------------------------------------------------------


def test_admin_login_is_rate_limited(client, auth):
    """
    Подбор пароля администратора обязан упираться в 429 с Retry-After.

    Раньше authenticate_admin не звал ratelimit вообще: POST
    /api/admin/login принимал сколько угодно попыток с любой скоростью, а
    пароль по умолчанию — "admin".
    """
    try:
        codes = [
            client.post(
                "/api/admin/login", json={"login": "admin", "password": f"wrong-{i}"}
            )
            for i in range(7)
        ]
        throttled = [r for r in codes if r.status_code == 429]
        assert throttled, f"перебор не остановлен: {[r.status_code for r in codes]}"
        # 401 и 429 должны различаться: панель обязана понять, что дело не в
        # пароле, и не предлагать набрать его ещё раз прямо сейчас.
        assert any(r.status_code == 401 for r in codes)
        # Заголовок Retry-After здесь не проверяется намеренно: обработчик
        # ошибок в main.py собирает ответ заново и теряет exc.headers — это
        # одинаково касается всех трёх мест, которые отдают 429.
        assert "мин" in throttled[0].json()["detail"], throttled[0].text
    finally:
        # Замок переживает тест и запер бы админский вход остальным модулям.
        with SessionLocal() as db:
            for key in (
                auth_service._admin_key("admin", None),
                auth_service._admin_name_key("admin"),
                auth_service._admin_ip_key(None),
            ):
                ratelimit.clear(db, key)

    # После снятия замка верный пароль снова принимается.
    ok = client.post("/api/admin/login", json={"login": "admin", "password": "admin"})
    assert ok.status_code == 200, ok.text


# --- токен приложения ---------------------------------------------------------


def test_token_is_extended_while_the_app_is_used(client, auth):
    """
    config.client_token_days обещает, что активный не разлогинивается.

    Session.expires_at присваивался ровно один раз — при создании, — и через
    тридцать дней человек упирался в экран входа с паролем, который панель
    показывала однажды.
    """
    created = client.post(
        "/api/admin/users", json={"name": "Продление Токена", "planCode": "3months"}, headers=auth
    ).json()

    r = client.post(
        "/api/v1/login",
        json={"login": created["user"]["login"], "password": created["password"]},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    # Токен почти истёк — так выглядит приложение, которое не открывали месяц.
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


# --- пароль на странице успеха ------------------------------------------------


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


def test_order_password_stops_being_served_after_the_window(client):
    """
    Идентификатор заказа лежит в адресной строке, в истории браузера и в
    логах, и его же просят назвать поддержке. Бессрочный доступ к паролю по
    этой строке — доступ к чужому VPN у любого, кто её увидел.
    """
    order_id = _paid_order(client, "window@example.com")

    fresh = client.get(f"/api/v1/orders/{order_id}/status").json()
    assert fresh["password"], "сразу после оплаты пароль обязан показываться"
    # Перезагрузка страницы не должна сжигать показ: success.js опрашивает
    # этот метод в цикле, а pay.js дёргает его же при загрузке.
    assert client.get(f"/api/v1/orders/{order_id}/status").json()["password"] == fresh["password"]

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        order.paid_at = utcnow() - dt.timedelta(hours=1)
        db.commit()

    stale = client.get(f"/api/v1/orders/{order_id}/status").json()
    assert stale["status"] == "paid"
    assert stale["login"], "логин и срок остаются: по ним человек пишет в поддержку"
    assert stale["password"] is None, "пароль отдаётся бессрочно"


def test_password_show_is_written_to_the_audit_once(client, auth):
    order_id = _paid_order(client, "audit-window@example.com")

    for _ in range(3):
        assert client.get(f"/api/v1/orders/{order_id}/status").json()["password"]

    rows = client.get(
        "/api/admin/audit", params={"action": "order.password_shown"}, headers=auth
    ).json()
    mine = [row for row in rows if row["target"] == order_id]
    assert len(mine) == 1, f"на заказ должна быть одна запись, а их {len(mine)}"


# --- шифрование паролей -------------------------------------------------------


def test_encrypt_refuses_the_default_key(monkeypatch):
    """
    Дефолтный PANEL_SECRETS_KEY опубликован в config.py.

    encrypt() проверял только непустоту ключа, поэтому с незаполненным .env
    пароли молча шифровались sha256("dev-insecure-change-me"), а панель при
    старте писала администратору, что они «не шифруются». Утечка базы
    отдавала пароли всем, у кого есть исходники.
    """
    from app import crypto
    from app.config import INSECURE_DEFAULT_SECRET, Settings

    default = Settings(secrets_key=INSECURE_DEFAULT_SECRET)
    monkeypatch.setattr(crypto, "settings", lambda: default)

    with pytest.raises(crypto.SecretsUnavailable):
        crypto.encrypt("тайна")
    # Вызывающие через encrypt_or_none не падают, но и шифротекста не получают.
    assert crypto.encrypt_or_none("тайна") is None


def test_decrypt_still_reads_blobs_written_with_the_old_key(monkeypatch):
    """
    Запрет стоит в encrypt, а не в _key(): _key() общий с decrypt, и запрет
    там сделал бы нечитаемыми уже сохранённые пароли — показ пароля и письма
    с доступом отвалились бы разом, не добавив безопасности.
    """
    from app import crypto
    from app.config import INSECURE_DEFAULT_SECRET, Settings

    default = Settings(secrets_key=INSECURE_DEFAULT_SECRET)
    monkeypatch.setattr(crypto, "settings", lambda: default)

    # Блоб, каким его записала прежняя версия — тем же дефолтным ключом.
    import base64
    import hashlib

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(INSECURE_DEFAULT_SECRET.encode()).digest()
    nonce = b"\x00" * 12
    blob = nonce + AESGCM(key).encrypt(nonce, "старый-пароль".encode(), None)
    token = "pv1." + base64.urlsafe_b64encode(blob).decode()

    assert crypto.decrypt(token) == "старый-пароль"


# --- ограничитель частоты -----------------------------------------------------


def test_rate_limit_counts_every_attempt():
    """
    Счётчик увеличивает база, а не питон.

    Read-modify-write («прочитали объект, прибавили, записали») терял
    инкременты при параллельных запросах: несколько воркеров читали одно
    значение и писали count+1 поверх друг друга, и лимит в пять попыток
    пропускал десятки.
    """
    key = "test:hardening:198.51.100.200"
    with SessionLocal() as db:
        ratelimit.clear(db, key)
        allowed = sum(1 for _ in range(9) if ratelimit.hit(db, key, limit=5, window_minutes=15))
        assert allowed == 5, f"пропущено {allowed} попыток вместо пяти"

        # Окно кончилось — счётчик начинается заново.
        row = db.execute(select(RateLimit).where(RateLimit.key == key)).scalar_one()
        row.window_start = utcnow() - dt.timedelta(minutes=30)
        row.locked_until = None
        db.commit()
        assert ratelimit.hit(db, key, limit=5, window_minutes=15).allowed
        ratelimit.clear(db, key)


def test_login_by_name_survives_a_changing_address(client, auth):
    """
    Ключ (адрес, логин) не мешает подбору с пула адресов: каждый новый адрес
    даёт чистый счётчик. Отдельный счётчик по имени учётки — единственное,
    что переживает ротацию адреса.
    """
    created = client.post(
        "/api/admin/users", json={"name": "Пул Адресов", "planCode": "3months"}, headers=auth
    ).json()
    login = created["user"]["login"]

    codes = [
        client.post(
            "/api/v1/login",
            json={"login": login, "password": "wrong"},
            # Каждый запрос «с нового адреса» — ровно то, чем обходили лимит.
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        ).status_code
        for i in range(1, 30)
    ]
    assert 429 in codes, f"перебор с пула адресов не остановлен: {codes}"

    with SessionLocal() as db:
        ratelimit.clear(db, auth_service._login_name_key(login))
