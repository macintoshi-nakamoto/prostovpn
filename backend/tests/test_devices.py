"""
Устройства: свой пир каждому и настоящее отключение.

Два обещания, которые до этого держались только на словах:

* «Отключить устройство» снимает пира именно этого устройства с узла, а не
  гасит токен и оставляет туннель работать;
* соседние устройства того же человека при этом не отваливаются.

Оба проверяются на поддельном SSH: настоящий узел тестам не нужен, важно,
какие ключи с него просят снять и в каком порядке.
"""

from __future__ import annotations

import datetime as dt
import itertools

import pytest
from sqlalchemy import select

from app import provisioning
from app.db import SessionLocal, init_db
from app.models import Provisioning, Server, Session, User, UserKey, utcnow
from app.security import hash_password
from app.services import devices as devices_service
from app.services import keys as keys_service

TEMPLATE = (
    "[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n"
    "[Peer]\nPublicKey = x\nEndpoint = 10.30.30.9:51820\n"
)


class FakeNode:
    """Узел, который помнит свои пиры вместо того, чтобы их поднимать."""

    def __init__(self) -> None:
        self.peers: set[str] = set()

    def add(self, _server, public_key, _address) -> None:
        self.peers.add(public_key)

    def remove(self, _server, public_key) -> None:
        self.peers.discard(public_key)


@pytest.fixture
def node(monkeypatch) -> FakeNode:
    fake = FakeNode()
    monkeypatch.setattr(provisioning, "add_peer_over_ssh", fake.add)
    monkeypatch.setattr(provisioning, "remove_peer_over_ssh", fake.remove)
    return fake


@pytest.fixture(scope="module")
def server_id() -> int:
    init_db()
    with SessionLocal() as db:
        server = Server(
            name="dev-node",
            country="Тест",
            country_code="XX",
            host="10.30.30.9",
            provisioning=Provisioning.SSH,
            awg_template=TEMPLATE,
            ssh_host="10.30.30.9",
            ssh_user="root",
            ssh_password="x",
            is_active=True,
        )
        db.add(server)
        db.commit()
        return server.id


def _user(login: str) -> int:
    with SessionLocal() as db:
        user = User(login=login, password_hash=hash_password("x"))
        db.add(user)
        db.commit()
        return user.id


# Токен в таблице уникален, а в тестах их заводится сколько угодно, в том
# числе несколько с одним пустым device_id, — поэтому просто счётчик.
_tokens = itertools.count(1)


def _session(user_id: int, device_id: str, platform: str = "windows") -> int:
    with SessionLocal() as db:
        session = Session(
            user_id=user_id,
            token_hash=f"hash-{next(_tokens)}",
            platform=platform,
            device_id=device_id,
            expires_at=utcnow() + dt.timedelta(days=30),
        )
        db.add(session)
        db.commit()
        return session.id


def test_each_device_gets_its_own_peer(server_id, node):
    """Два устройства одного человека — два разных ключа и два адреса."""
    user_id = _user("dev-two")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        laptop = keys_service.issue_key(db, user, server, device_id="laptop")
        phone = keys_service.issue_key(db, user, server, device_id="phone")

    assert laptop.public_key != phone.public_key
    assert laptop.address != phone.address
    assert node.peers == {laptop.public_key, phone.public_key}


def test_disconnect_removes_only_that_device(server_id, node):
    """
    Отключение снимает пира одного устройства и не трогает соседей.

    Ровно то, ради чего пир вообще стал принадлежать устройству: пока он был
    общим, снять его значило отключить человека целиком.
    """
    user_id = _user("dev-disconnect")
    laptop_session = _session(user_id, "laptop")
    _session(user_id, "phone")

    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        laptop = keys_service.issue_key(db, user, server, device_id="laptop")
        phone = keys_service.issue_key(db, user, server, device_id="phone")

    with SessionLocal() as db:
        target = db.get(Session, laptop_session)
        assert devices_service.disconnect(db, target) == []

    assert node.peers == {phone.public_key}, "сняли не тот пир или снесли оба"

    with SessionLocal() as db:
        rows = {
            key.device_id: key.revoked_at
            for key in db.scalars(select(UserKey).where(UserKey.user_id == user_id))
        }
        assert rows["laptop"] is not None, "ключ отключённого устройства остался живым"
        assert rows["phone"] is None, "соседнее устройство отключилось заодно"
        assert db.get(Session, laptop_session).revoked_at is not None
    assert laptop.public_key not in node.peers


def test_disconnect_keeps_shared_key_while_someone_uses_it(server_id, node):
    """
    Общий «ключ учётки» не снимается, пока на нём сидит ещё кто-то.

    Так ходят приложения старых версий: идентификатора установки они не
    присылают, пир у них один на всех. Отключить один такой вход и уронить
    заодно остальные — хуже, чем не отключить пира вовсе: токен всё равно
    погашен, и приложение попросит войти заново.
    """
    user_id = _user("dev-legacy")
    first = _session(user_id, "")
    second = _session(user_id, "")

    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        shared = keys_service.issue_key(db, user, server)

    with SessionLocal() as db:
        devices_service.disconnect(db, db.get(Session, first))
    assert shared.public_key in node.peers, "общий пир сняли из-под второго входа"

    with SessionLocal() as db:
        devices_service.disconnect(db, db.get(Session, second))
    assert shared.public_key not in node.peers, "последний вход ушёл, а пир остался"


def test_device_without_its_own_peer_falls_back_to_the_account_key(server_id, node):
    """
    Устройство, вошедшее до появления пиров на устройство, не теряет туннель.

    Ровно тот переход, ради которого написана подмена в _servers_out: сессия
    уже есть и с device_id, а ключ у человека пока один — общий. Пустой
    список стран в этот момент означал бы «доступ закрыт», и клиент опустил
    бы рабочий туннель.
    """
    from app.api_client import _servers_out
    from app.services import billing

    user_id = _user("dev-fallback")
    session_id = _session(user_id, "laptop")

    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        billing.grant_subscription(db, user, days=30)
        shared = keys_service.issue_key(db, user, server)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        out = _servers_out(db, user, db.get(Session, session_id))
        # Именно по этому узлу: база у прогона общая, и соседние модули
        # заводят в ней свои серверы.
        mine = [s for s in out if s.id == server_id]
        assert [s.config for s in mine] == [shared.config], "устройство осталось без конфига"


def test_parallel_traffic_sync_does_not_double_count(server_id, node, monkeypatch):
    """
    Два обхода одного узла разом не задваивают расход.

    Фоновый цикл и кнопка «Синхронизировать» в панели — два пути к одному
    sync_server_traffic из разных сессий. Раньше расход считался
    read-modify-write по ORM-объекту: оба читали прежний замер, оба брали
    одну и ту же дельту и оба прибавляли — гигабайт превращался в два.
    Замок на сервер сериализует обход: второй заход видит уже записанный
    замер, его дельта — ноль.
    """
    import threading

    from app.models import GB
    from app.services import billing, traffic

    user_id = _user("dev-traffic-race")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        billing.grant_subscription(db, user, days=30)
        key = keys_service.issue_key(db, user, server, device_id="counter")
        public_key = key.public_key

    # Узел рапортует гигабайт принятого. Формат awg dump: первая строка —
    # интерфейс (её отбрасывают по позиции), дальше по восемь полей на пира.
    dump = (
        "iface_pubkey\t(none)\toff\toff\t0\t0\t0\toff\n"
        f"{public_key}\t(none)\t10.30.30.9:51820\t10.8.0.2/32\t0\t{GB}\t0\t25\n"
    )
    monkeypatch.setattr(traffic.provisioning, "run_over_ssh", lambda *_a, **_k: dump)

    # Два одновременных обхода в разных сессиях, синхронный старт барьером.
    barrier = threading.Barrier(2)

    def run_sync():
        barrier.wait()
        with SessionLocal() as db:
            traffic.sync_server_traffic(db, db.get(Server, server_id))

    threads = [threading.Thread(target=run_sync) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with SessionLocal() as db:
        used = db.get(User, user_id).traffic_used_bytes
    assert used == GB, f"расход задвоился: {used} вместо {GB}"


def test_login_returns_the_peer_provisioned_during_that_same_login(server_id, node):
    """
    Свежий пир, заведённый на входе, попадает в ответ этого же входа.

    ensure_keys добавляет UserKey по внешнему ключу, не трогая уже
    загруженную коллекцию user.keys, а сессия живёт с expire_on_commit=False
    — коммит внутри ensure_keys её не перечитывает. Без явного сброса кэша
    _servers_out итерировал старый список без только что созданного пира и
    отдавал устройству пустой список стран ровно на входе, когда пир уже
    готов. Проверяем именно этот путь: чистое устройство, вход, непустой
    список.
    """
    from app.api_client import _provision_for_login, _servers_out
    from app.services import billing

    user_id = _user("dev-fresh-login")
    session_id = _session(user_id, "brand-new")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        billing.grant_subscription(db, user, days=30)
        # Ключей на этом узле у устройства пока нет — их заведёт вход.

    with SessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(Session, session_id)
        _provision_for_login(db, user, session)
        out = _servers_out(db, user, session)
        mine = [s for s in out if s.id == server_id]
        assert mine, "вход завёл пира, но список серверов на входе оказался пустым"
        assert mine[0].config, "сервер в списке есть, а конфига нет"


def test_unreachable_node_still_kills_the_token_and_revokes_the_key(server_id, node, monkeypatch):
    """
    Узел не ответил — сессия погашена, а ключ ВСЁ РАВНО отозван.

    Оставлять живой токен из-за недоступного узла нельзя: это худший из
    исходов, доступ остаётся и в приложении, и в туннеле.

    Ключ обязан стать отозванным, даже когда снять пира по SSH не вышло.
    Иначе сверка reconcile_peers считает его живым и пира не снимает — и
    отключённое устройство (например, украденный телефон) остаётся в VPN
    навсегда, стоило узлу разок не ответить. Отзыв ключа передаёт снятие
    сверке: она увидит на узле пира без живого ключа и снимет его.
    """
    user_id = _user("dev-offline")
    session_id = _session(user_id, "laptop")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        keys_service.issue_key(db, user, server, device_id="laptop")

    def refuse(*_args, **_kwargs):
        raise RuntimeError("узел не ответил")

    monkeypatch.setattr(provisioning, "remove_peer_over_ssh", refuse)

    with SessionLocal() as db:
        problems = devices_service.disconnect(db, db.get(Session, session_id))
        assert problems and "dev-node" in problems[0]
        assert db.get(Session, session_id).revoked_at is not None

    with SessionLocal() as db:
        key = db.scalar(
            select(UserKey).where(UserKey.user_id == user_id, UserKey.device_id == "laptop")
        )
        assert key.revoked_at is not None, "ключ остался живым — reconcile не снимет пира, доступ вечен"


def test_background_provision_does_not_resurrect_an_unlinked_device(server_id, node):
    """
    Фоновая доза ключей не воскрешает пира отвязанного устройства.

    Сценарий гонки: /servers заметил недостающий ключ и поставил фоновую
    задачу на это устройство; в те же секунды человек отвязал устройство в
    кабинете (сессия погашена, ключи отозваны). Раньше фоновая задача видела
    только «доступ у аккаунта есть» и заводила пира заново — отключённый
    телефон возвращался в VPN. Теперь задача проверяет, что у устройства
    ещё есть живая сессия.
    """
    from app.api_client import _provision_missing_keys
    from app.services import billing

    user_id = _user("dev-resurrect")
    session_id = _session(user_id, "ghost")
    with SessionLocal() as db:
        user, server = db.get(User, user_id), db.get(Server, server_id)
        billing.grant_subscription(db, user, days=30)
        keys_service.issue_key(db, user, server, device_id="ghost")

    # Отвязка устройства: сессия погашена, пир снят, ключ отозван.
    with SessionLocal() as db:
        devices_service.disconnect(db, db.get(Session, session_id))
    assert node.peers == set(), "после отвязки пира на узле быть не должно"

    # Фоновая задача, поставленная до отвязки, выполняется уже после неё.
    _provision_missing_keys(user_id, "ghost")

    assert node.peers == set(), "фоновая доза воскресила пира отвязанного устройства"
    with SessionLocal() as db:
        live = db.scalars(
            select(UserKey).where(
                UserKey.user_id == user_id,
                UserKey.device_id == "ghost",
                UserKey.revoked_at.is_(None),
            )
        ).all()
        assert live == [], "у отвязанного устройства снова появился живой ключ"
