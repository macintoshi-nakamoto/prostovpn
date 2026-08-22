"""
Ключ AmneziaVPN как устройство и очередь подписок.

Первая часть — обещания списка «Подключённые устройства»:

* ключ, через который пошёл трафик, появляется в списке устройств и
  занимает место наравне с телефоном с приложением;
* «Отключить» снимает пира с узла, и ни продление, ни фоновая раздача
  не возвращают его без явного «включить»;
* «включить» возвращает ТОТ ЖЕ пир: ссылка, вставленная в Amnezia,
  продолжает работать без переустановки.

Вторая часть — очередь оплаченных периодов:

* смена тарифа не съедает оставшиеся дни: новый период встаёт за текущим,
  и до его начала действуют лимиты старого тарифа;
* покупка во время пробного включается сразу — бесплатные дни не заставляют
  досиживать пробные лимиты после оплаты.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app import provisioning
from app.db import SessionLocal, init_db
from app.models import (
    HANDSHAKE_WINDOW,
    Plan,
    Provisioning,
    Server,
    Subscription,
    User,
    UserKey,
    utcnow,
)
from app.public_api import _ios_device_rows
from app.security import hash_password
from app.services import billing, ios
from app.services import keys as keys_service


class FakeNode:
    def __init__(self) -> None:
        self.peers: set[str] = set()
        self.placed: dict[str, str] = {}
        self.removed_from: dict[str, str] = {}

    def add(self, _server, public_key, _address, *, interface="awg0") -> None:
        self.peers.add(public_key)
        self.placed[public_key] = interface

    def remove(self, _server, public_key, *, interface="awg0") -> None:
        self.peers.discard(public_key)
        self.removed_from[public_key] = interface


@pytest.fixture
def node(monkeypatch) -> FakeNode:
    fake = FakeNode()
    monkeypatch.setattr(provisioning, "add_peer_over_ssh", fake.add)
    monkeypatch.setattr(provisioning, "remove_peer_over_ssh", fake.remove)
    return fake


TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "[Peer]\nPublicKey = x\nEndpoint = 10.40.40.9:51820\n"
)


@pytest.fixture(scope="module")
def server_id() -> int:
    init_db()
    with SessionLocal() as db:
        server = Server(
            name="ios-node",
            country="Тест",
            country_code="XY",
            host="10.40.40.9",
            provisioning=Provisioning.SSH,
            awg_template=TEMPLATE,
            ssh_host="10.40.40.9",
            ssh_user="root",
            ssh_password="x",
            is_active=True,
        )
        db.add(server)
        db.commit()
        return server.id


def _paid_user(login: str, days: int = 30) -> int:
    """Учётка с действующей платной подпиской и включёнными ключами iPhone."""
    with SessionLocal() as db:
        user = User(login=login, password_hash=hash_password("x"), ios_access=True)
        db.add(user)
        db.flush()
        db.add(
            Subscription(
                user_id=user.id,
                plan="basic",
                price=300,
                period_days=days,
                starts_at=utcnow() - dt.timedelta(days=1),
                expires_at=utcnow() + dt.timedelta(days=days),
            )
        )
        db.commit()
        return user.id


def _slot_keys(db, user_id: int, server_id: int) -> list[UserKey]:
    return list(
        db.scalars(
            select(UserKey).where(
                UserKey.user_id == user_id,
                UserKey.server_id == server_id,
                UserKey.device_id == "ios-1",
            )
        )
    )


# --- ключ как устройство --------------------------------------------------------


def test_ios_key_becomes_a_device_only_after_traffic(server_id, node):
    user_id = _paid_user("ios-dev-1")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.sync(db, user)
        db.refresh(user)
        now = utcnow()

        # Ключ выдан, но не вставлен: устройства нет.
        assert _ios_device_rows(user, now) == []

        # Пошёл трафик — появилась строка устройства, «в сети».
        key = _slot_keys(db, user_id, server_id)[0]
        key.last_handshake_at = now - dt.timedelta(seconds=30)
        db.commit()
        db.refresh(user)

        rows = _ios_device_rows(user, now)
        assert len(rows) == 1
        row = rows[0]
        assert row.kind == "ios_key" and row.slot == 1
        # Отрицательный id: номера сессий с ним не пересекаются.
        assert row.id == -1
        assert row.is_connected is True

        # Рукопожатие устарело — строка осталась, но уже не «в сети».
        key.last_handshake_at = now - HANDSHAKE_WINDOW - dt.timedelta(minutes=2)
        db.commit()
        db.refresh(user)
        rows = _ios_device_rows(user, now)
        assert len(rows) == 1 and rows[0].is_connected is False


def test_disconnect_removes_peer_and_survives_provisioning(server_id, node):
    user_id = _paid_user("ios-dev-2")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.sync(db, user)
        db.refresh(user)
        key = _slot_keys(db, user_id, server_id)[0]
        public_key = key.public_key
        config = key.config
        key.last_handshake_at = utcnow()
        db.commit()
        assert public_key in node.peers

        # «Отключить» на строке устройства: пир снят, строки устройств нет.
        db.refresh(user)
        ios.disconnect_key(db, user, 1)
        db.refresh(user)
        assert public_key not in node.peers
        assert _ios_device_rows(user, utcnow()) == []

        # Ни раздача при входе, ни продление не возвращают пира сами.
        keys_service.ensure_keys(db, user)
        ios.sync(db, user)
        db.refresh(user)
        assert public_key not in node.peers
        assert all(k.revoked_at is not None for k in _slot_keys(db, user_id, server_id))

        # «Включить» возвращает тот же пир и ту же ссылку.
        ios.reconnect_key(db, user, 1)
        db.refresh(user)
        fresh = _slot_keys(db, user_id, server_id)[0]
        assert public_key in node.peers
        assert fresh.public_key == public_key and fresh.config == config
        assert fresh.revoked_at is None and fresh.disconnected_at is None

        # Устройством ключ станет снова после нового рукопожатия, не раньше.
        assert _ios_device_rows(db.get(User, user_id), utcnow()) == []


def test_disconnected_key_is_shown_and_counts_a_slot(server_id, node):
    user_id = _paid_user("ios-dev-3")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.sync(db, user)
        db.refresh(user)
        ios.disconnect_key(db, user, 1)
        db.refresh(user)

        # Рабочих ссылок нет, отключённый ключ виден с пометкой.
        assert ios.keys(user) == []
        off = [k for k in ios.keys(user, include_disconnected=True) if k.disconnected]
        assert len(off) >= 1 and all(not k.is_active for k in off)

        # Слот занят: свободные номера начинаются со второго.
        assert ios.free_slot(user) == 2


# --- очередь подписок -----------------------------------------------------------


def _plan(db, code: str, name: str, kopecks: int, days: int) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        plan = Plan(code=code, name=name, period_days=days)
        db.add(plan)
    plan.set_price(kopecks)
    plan.period_days = days
    db.commit()
    db.refresh(plan)
    return plan


def test_same_plan_extend_prolongs_visibly(server_id):
    """Продление того же тарифа продлевает период, а не плодит очередь."""
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)

        user = User(login="extend-1", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        first = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        first_id, first_end = first.id, first.expires_at

        # Ещё раз тот же тариф — тот же период, срок сдвинулся на 30 дней.
        again = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        db.refresh(user)
        assert again.id == first_id
        assert again.expires_at == first_end + dt.timedelta(days=30)

        # Очереди нет, общий конец сразу вырос — это и есть «продление видно».
        assert user.upcoming_subscriptions() == []
        assert user.access_days_left() >= 59
        assert user.active_subscription().id == first_id


def test_plan_change_queues_after_paid_days(server_id):
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)
        pro = _plan(db, "q-pro", "Годовая", 149_900, 365)

        user = User(login="queue-1", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        first = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        first_end = first.expires_at

        # Смена тарифа: новый период встаёт за текущим, а не поверх него.
        second = billing.grant_subscription(db, user, days=365, plan=pro, price=1499)
        db.refresh(user)
        assert second.starts_at == first_end
        assert second.expires_at == first_end + dt.timedelta(days=365)

        # Пока старые дни не дожиты, действует старый тариф.
        current = user.active_subscription()
        assert current.id == first.id and current.plan == "q-basic"
        assert user.current_plan().code == "q-basic"

        # Очередь и общий конец доступа видны; «осталось» считает весь доступ.
        queued = user.upcoming_subscriptions()
        assert [s.id for s in queued] == [second.id]
        assert user.access_expires_at() == second.expires_at
        assert user.access_days_left() >= 30 + 365 - 1

        # Когда старый срок кончится, в полную силу вступает новый.
        later = first_end + dt.timedelta(hours=1)
        assert user.active_subscription(later).id == second.id
        assert user.current_plan(later).code == "q-pro"


def test_queue_stays_one_period_on_repeated_change(server_id):
    """Повторная смена тарифа не копит каскад — очередь ровно одна."""
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)
        pro = _plan(db, "q-pro", "Годовая", 149_900, 365)
        half = _plan(db, "q-half", "Полугодовая", 89_900, 180)

        user = User(login="queue-2", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        billing.grant_subscription(db, user, days=365, plan=pro, price=1499)
        # Передумали: другой апгрейд заменяет прежний запланированный, а не
        # встаёт третьим слоем.
        billing.grant_subscription(db, user, days=180, plan=half, price=899)
        db.refresh(user)

        upcoming = user.upcoming_subscriptions()
        assert len(upcoming) == 1
        assert upcoming[0].plan == "q-half"
        # Старый тариф по-прежнему идёт, а не потерян.
        assert user.active_subscription().plan == "q-basic"


def test_free_trial_does_not_queue_behind_paid(server_id):
    """Пробный не пристраивается к живому платному доступу."""
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)
        trial = _plan(db, "q-trial", "Пробный", 0, 2)

        user = User(login="trial-1", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        paid = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        # Пробный при живой подписке — ничего не заводит и очередь не двигает.
        got = billing.grant_subscription(db, user, days=2, plan=trial, price=0)
        db.refresh(user)
        assert got.id == paid.id
        assert user.upcoming_subscriptions() == []
        assert [s for s in user.subscriptions if not s.is_cancelled] == [paid]


def test_paid_purchase_during_trial_starts_now(server_id):
    """Оплата во время пробного вступает сразу, а не встаёт за пробным."""
    with SessionLocal() as db:
        trial = _plan(db, "q-trial", "Пробный", 0, 2)
        year = _plan(db, "q-year", "Годовая", 149_900, 365)

        user = User(login="trial-2", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        # Человек на пробном.
        billing.grant_subscription(db, user, days=2, plan=trial, price=0)
        # Покупает годовой — он должен работать НЕМЕДЛЕННО, на полных лимитах.
        billing.grant_subscription(db, user, days=365, plan=year, price=1499)
        db.refresh(user)

        act = user.active_subscription()
        assert act is not None and act.plan == "q-year"
        assert user.current_plan().code == "q-year"
        assert user.upcoming_subscriptions() == []


def test_admin_extend_visibly_adds_days_near_expiry(server_id):
    """
    Симптом из отчёта: подписка на исходе показывает 0 дней, «продлить» её
    не меняет. С продлением того же тарифа дни обязаны вырасти сразу.
    """
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)
        user = User(login="near-expiry", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        # Период кончается через 3 часа — «осталось 0 дней».
        sub = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        sub.starts_at = utcnow() - dt.timedelta(days=30)
        sub.expires_at = utcnow() + dt.timedelta(hours=3)
        db.commit()
        db.refresh(user)
        assert user.access_days_left() == 0

        # Администратор продлевает тем же тарифом на 30 дней.
        billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        db.refresh(user)
        assert user.access_days_left() >= 30
        assert user.has_access() is True


def test_collapse_repairs_paid_stuck_behind_trial(server_id):
    """Чистка активирует оплаченный тариф, застрявший за пробным."""
    with SessionLocal() as db:
        trial = _plan(db, "q-trial", "Пробный", 0, 2)
        year = _plan(db, "q-year", "Годовая", 149_900, 365)

        user = User(login="stuck-1", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        now = utcnow()
        # Воспроизводим порчу: пробный идёт, годовой заперт в будущем за ним.
        db.add(
            Subscription(
                user_id=user.id, plan="q-trial", price=0, period_days=2,
                starts_at=now - dt.timedelta(days=1), expires_at=now + dt.timedelta(days=1),
            )
        )
        db.add(
            Subscription(
                user_id=user.id, plan="q-year", plan_id=year.id, price=1499, period_days=365,
                starts_at=now + dt.timedelta(days=1), expires_at=now + dt.timedelta(days=366),
            )
        )
        db.commit()
        db.refresh(user)
        # До чистки человек на пробном, хотя оплатил годовой.
        assert user.active_subscription().plan == "q-trial"

        fixed = billing.collapse_corrupted_queues(db)
        db.refresh(user)
        logins = [f["login"] for f in fixed]
        assert "stuck-1" in logins
        # Теперь идёт оплаченный годовой, очереди нет, доступ есть.
        assert user.active_subscription().plan == "q-year"
        assert user.upcoming_subscriptions() == []
        assert user.has_access() is True
        # Повтор ничего не трогает — идемпотентно.
        assert all(f["login"] != "stuck-1" for f in billing.collapse_corrupted_queues(db))


def test_account_api_shows_ios_device_and_disconnect_cycle(server_id, node):
    """Весь путь через HTTP: устройство появилось → отключили → включили."""
    from fastapi.testclient import TestClient

    from app.main import app

    user_id = _paid_user("ios-http-1")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ios.sync(db, user)
        db.refresh(user)
        key = _slot_keys(db, user_id, server_id)[0]
        key.last_handshake_at = utcnow()
        db.commit()

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/login",
            json={"login": "ios-http-1", "password": "x", "platform": "web", "device_id": "b1"},
        )
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['token']}"}

        account = client.get("/api/v1/account", headers=headers).json()
        rows = [d for d in account["devices"] if d["kind"] == "ios_key"]
        assert len(rows) == 1
        assert rows[0]["slot"] == 1 and rows[0]["id"] == -1
        assert rows[0]["is_connected"] is True
        assert account["ios"]["keys"], "рабочая ссылка должна быть в списке"
        link_before = account["ios"]["keys"][0]["vpn_url"]
        # Поля очереди подписок присутствуют, даже когда очередь пуста.
        assert account["upcoming"] == []
        assert account["expires_total_at"] is not None

        # «Отключить»: строка устройства пропала, ключ переехал в отключённые.
        account = client.post("/api/v1/account/ios/keys/1/disconnect", headers=headers).json()
        assert [d for d in account["devices"] if d["kind"] == "ios_key"] == []
        assert account["ios"]["keys"] == []
        # Строк — по одной на страну, слот при этом один.
        off = account["ios"]["disconnected_keys"]
        assert {k["slot"] for k in off} == {1}
        assert all(k["disconnected"] for k in off)
        # Слот занят и после отключения: «2 из 5» не съезжает.
        assert account["ios"]["keys_count"] == 1

        # «Включить»: та же ссылка вернулась; устройством станет после трафика.
        account = client.post("/api/v1/account/ios/keys/1/enable", headers=headers).json()
        assert account["ios"]["disconnected_keys"] == []
        assert account["ios"]["keys"][0]["vpn_url"] == link_before
        assert [d for d in account["devices"] if d["kind"] == "ios_key"] == []


def test_purchase_during_trial_starts_immediately(server_id):
    with SessionLocal() as db:
        basic = _plan(db, "q-basic", "Базовый", 19_900, 30)

        user = User(login="queue-trial", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        now = utcnow()
        db.add(
            Subscription(
                user_id=user.id,
                plan="trial",
                price=0,
                period_days=2,
                starts_at=now - dt.timedelta(hours=1),
                expires_at=now + dt.timedelta(days=2),
            )
        )
        db.commit()

        # Пробные дни ничего не стоят: купленный тариф начинается сразу.
        paid = billing.grant_subscription(db, user, days=30, plan=basic, price=199)
        db.refresh(user)
        assert paid.starts_at <= utcnow()
        assert user.active_subscription().id == paid.id
        assert user.current_plan().code == "q-basic"
        assert user.upcoming_subscriptions() == []
