"""
Оповещения о падении узла.

Главное, что здесь проверяется, — кому уходит сообщение. Список адресатов
берётся только из настройки, и ни один пользователь в него попасть не
должен: цена ошибки — рассылка «узел лежит» всей базе.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Provisioning, Server, User, utcnow
from app.security import hash_password
from app.services import alerts


@pytest.fixture(scope="module", autouse=True)
def schema():
    init_db()


@pytest.fixture()
def node():
    with SessionLocal() as db:
        server = Server(
            name="alerts-nl",
            country="Нидерланды",
            country_code="NL",
            host="10.90.90.1",
            provisioning=Provisioning.SSH,
            is_active=True,
        )
        db.add(server)
        # Живой человек в базе: если код когда-нибудь начнёт брать адресатов
        # из пользователей, тест это увидит.
        db.add(User(login="alerts-victim", password_hash=hash_password("x"), telegram_id=999777))
        db.commit()
        server_id = server.id
    yield server_id
    with SessionLocal() as db:
        row = db.get(Server, server_id)
        if row is not None:
            db.delete(row)
        victim = db.query(User).filter(User.login == "alerts-victim").one_or_none()
        if victim is not None:
            db.delete(victim)
        db.commit()


def _sent(monkeypatch) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    monkeypatch.setattr(alerts.telegram, "send", lambda chat_id, text: out.append((chat_id, text)))
    return out


def _lay_down(server_id: int, minutes: int) -> None:
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        server.down_since = utcnow() - dt.timedelta(minutes=minutes)
        server.traffic_error = "ssh: connection refused"
        db.commit()


def test_адресаты_только_из_настройки(node, monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111, 222")
    assert alerts.admin_chats() == [111, 222]

    monkeypatch.setattr(settings(), "alert_chat_ids", "")
    assert alerts.admin_chats() == []

    monkeypatch.setattr(settings(), "alert_chat_ids", "333;мусор;444")
    assert alerts.admin_chats() == [333, 444]


def test_молчим_пока_узел_не_належал_порог(node, monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111")
    sent = _sent(monkeypatch)

    _lay_down(node, minutes=1)
    with SessionLocal() as db:
        assert alerts.check_nodes(db) == []
    assert sent == []


def test_шлём_один_раз_и_только_админам(node, monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111,222")
    sent = _sent(monkeypatch)

    _lay_down(node, minutes=10)
    with SessionLocal() as db:
        assert alerts.check_nodes(db) == [f"down:alerts-nl"]

    assert [chat for chat, _ in sent] == [111, 222]
    assert "Нидерланды" in sent[0][1]
    # Адрес узла в сообщении не нужен, но и не запрещён — проверяем главное:
    # никаких посторонних адресатов.
    assert 999777 not in [chat for chat, _ in sent]

    # Второй заход по тому же падению молчит.
    sent.clear()
    with SessionLocal() as db:
        assert alerts.check_nodes(db) == []
    assert sent == []


def test_сообщаем_о_возвращении(node, monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111")
    sent = _sent(monkeypatch)

    _lay_down(node, minutes=10)
    with SessionLocal() as db:
        alerts.check_nodes(db)
    sent.clear()

    with SessionLocal() as db:
        server = db.get(Server, node)
        server.down_since = None
        server.last_ok_at = utcnow()
        server.traffic_error = None
        db.commit()

    with SessionLocal() as db:
        assert alerts.check_nodes(db) == [f"up:alerts-nl"]
    assert len(sent) == 1
    assert "снова отвечает" in sent[0][1]


def test_без_настройки_никому_не_шлём(node, monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "")
    sent = _sent(monkeypatch)

    _lay_down(node, minutes=10)
    with SessionLocal() as db:
        assert alerts.check_nodes(db) == []
    assert sent == []

    # И отметку не ставим — значит скажем, как только адресаты появятся.
    with SessionLocal() as db:
        assert db.get(Server, node).alert_sent_at is None


def test_статус_для_сайта_без_адресов(node, monkeypatch):
    _lay_down(node, minutes=10)
    with SessionLocal() as db:
        status = alerts.public_status(db)

    mine = [row for row in status["servers"] if row["name"] == "alerts-nl"]
    assert mine and mine[0]["up"] is False
    assert mine[0]["country"] == "Нидерланды"
    assert "host" not in mine[0]
    assert status["down"] >= 1
    assert status["ok"] is False


def _user_with_limit(login: str, limit: int):
    """Человек с тарифом на N устройств — тариф берётся из подписки."""
    import datetime as dt2

    from app.models import Plan, Subscription

    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "share-test").one_or_none()
        if plan is None:
            plan = Plan(code="share-test", name="Проверка", period_days=30, price=0,
                        device_limit=limit)
            db.add(plan)
            db.flush()
        user = User(login=login, password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        db.add(Subscription(user_id=user.id, plan=plan.code, plan_id=plan.id, price=0,
                            currency="RUB", period_days=30, auto_renew=False,
                            starts_at=utcnow() - dt2.timedelta(days=1),
                            expires_at=utcnow() + dt2.timedelta(days=29),
                            is_cancelled=False))
        db.commit()
        return user.id


def test_общий_ключ_замечается_не_сразу(monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111")
    sent = _sent(monkeypatch)
    uid = _user_with_limit("share-one", 1)
    many = {uid: {"1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"}}

    # Первые два обхода молчат: всплеск бывает от переключения сети.
    with SessionLocal() as db:
        assert alerts.check_sharing(db, many) == []
    with SessionLocal() as db:
        assert alerts.check_sharing(db, many) == []
    assert sent == []

    # Третий подряд — говорим админу, и ровно один раз.
    with SessionLocal() as db:
        assert alerts.check_sharing(db, many) == ["share:" + db.get(User, uid).public_id]
    assert len(sent) == 1 and sent[0][0] == 111
    assert "share-one" in sent[0][1]

    sent.clear()
    with SessionLocal() as db:
        assert alerts.check_sharing(db, many) == []
    assert sent == []


def test_запас_в_один_адрес_не_тревожит(monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111")
    sent = _sent(monkeypatch)
    uid = _user_with_limit("share-two", 1)
    # Лимит 1, запас 1 — два адреса это норма: телефон между Wi-Fi и LTE.
    ok = {uid: {"1.1.1.1", "2.2.2.2"}}
    for _ in range(4):
        with SessionLocal() as db:
            assert alerts.check_sharing(db, ok) == []
    assert sent == []
    with SessionLocal() as db:
        assert db.get(User, uid).shared_strikes == 0
        assert db.get(User, uid).shared_ips == 2


def test_серия_обнуляется_когда_лишние_ушли(monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111")
    _sent(monkeypatch)
    uid = _user_with_limit("share-three", 1)
    many = {uid: {"1.1.1.1", "2.2.2.2", "3.3.3.3"}}
    with SessionLocal() as db:
        alerts.check_sharing(db, many)
    with SessionLocal() as db:
        assert db.get(User, uid).shared_strikes == 1
    with SessionLocal() as db:
        alerts.check_sharing(db, {uid: {"1.1.1.1"}})
    with SessionLocal() as db:
        assert db.get(User, uid).shared_strikes == 0
