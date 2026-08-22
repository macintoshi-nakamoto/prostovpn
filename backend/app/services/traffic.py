"""
Учёт трафика: снимаем счётчики пиров с серверов по SSH.

`awg show <iface> dump` печатает по строке на пира с абсолютными rx/tx с
момента поднятия интерфейса. Мы храним предыдущий замер и копим разницу:
после перезагрузки сервера счётчик уезжает в ноль, и абсолютное значение
дало бы отрицательный прирост либо потерю всей истории.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from .. import provisioning
from ..models import (
    EndpointState,
    Provisioning,
    Server,
    TrafficSample,
    User,
    UserKey,
    utcnow,
)

log = logging.getLogger("panel.traffic")

# Интерфейс AmneziaWG на сервере — тот же, что использует provisioning.
INTERFACE = "awg0"

# Пауза перед снятием «лишнего» пира: даёт закоммититься выдаче, идущей
# параллельно (см. reconcile_peers). Секунды, а не десятки: коммит public_key
# в issue_key следует за awg-set почти сразу, а сверка идёт раз в минуту.
RECONCILE_GRACE_SECONDS = 3


# Строка пира в `awg show dump` ровно из восьми полей:
# public_key, preshared_key, endpoint, allowed_ips, latest_handshake, rx, tx,
# persistent_keepalive.
_PEER_FIELDS = 8


def _parse_dump(text: str) -> dict[str, dict[str, int]]:
    """
    Разбирает вывод `awg show <iface> dump`.

    Первая строка — сам интерфейс, и её надо отбросить явно. Отбрасывать её
    по числу полей нельзя, и это стоило нам настоящей поломки: у обычного
    WireGuard в ней четыре поля, а AmneziaWG дописывает туда параметры
    обфускации (Jc, Jmin, Jmax, S1, S2, H1..H4) — получается двенадцать.
    Проверка «меньше восьми полей — пропустить» такую строку пропускала
    внутрь, и первым полем, то есть «публичным ключом пира», становился
    ПРИВАТНЫЙ КЛЮЧ СЕРВЕРА.

    Учёт трафика от этого не страдал — выдуманный ключ ни с чьим не
    совпадал, — но сверка пиров каждую минуту пыталась снять с узла ключ,
    которого там нет, и писала его начало в журнал.

    Поэтому: первая строка отбрасывается по позиции, а от пира требуется
    ровно восемь полей.
    """
    peers: dict[str, dict[str, int]] = {}
    lines = text.splitlines()
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != _PEER_FIELDS:
            continue
        public_key, _psk, _endpoint, _allowed, handshake, rx, tx, _keepalive = parts
        try:
            peers[public_key.strip()] = {
                "handshake": int(handshake),
                "rx": int(rx),
                "tx": int(tx),
            }
        except ValueError:
            continue
    return peers


# Замок на сервер: одновременный обход одного узла двумя путями (фоновый
# цикл и кнопка «Синхронизировать» в панели) — это read-modify-write по
# traffic_used_bytes из двух сессий. Оба читают старый расход, оба считают
# дельту от одного и того же прежнего замера и оба прибавляют — расход
# задваивается, а параллельный сброс при продлении затирается. Замок
# сериализует обход конкретного узла; разные узлы друг друга не ждут.
_server_locks: dict[int, "threading.Lock"] = {}
_server_locks_guard = None


def _lock_for_server(server_id: int) -> "threading.Lock":
    global _server_locks_guard
    import threading

    if _server_locks_guard is None:
        _server_locks_guard = threading.Lock()
    with _server_locks_guard:
        lock = _server_locks.get(server_id)
        if lock is None:
            lock = threading.Lock()
            _server_locks[server_id] = lock
        return lock


def sync_server_traffic(db: OrmSession, server: Server) -> dict[str, object]:
    """
    Обновляет расход трафика по всем пирам одного сервера.

    Ошибку не поднимаем наверх, а записываем в сам сервер: один недоступный
    сервер не должен ронять обход остальных.

    Обход одного узла сериализован замком: параллельный запуск задвоил бы
    расход, посчитав одну и ту же дельту дважды из двух сессий.
    """
    if server.provisioning != Provisioning.SSH:
        return {"server_id": server.id, "skipped": "общий ключ — счётчиков по людям нет"}

    with _lock_for_server(server.id):
        return _sync_server_traffic_locked(db, server)


def server_interfaces(server: Server) -> list[str]:
    """
    Интерфейсы узла, с которых снимаем счётчики.

    Исторический awg0 присутствует всегда, даже если точки входа ещё не
    заведены: на нём живут ключи, у которых `endpoint_id` пуст.
    """
    from ..models import EndpointKind

    names = [INTERFACE]
    for endpoint in server.endpoints:
        if endpoint.kind != EndpointKind.AWG:
            continue
        # Черновик на узле ещё не поднят, выведенный — уже погашен. Ждать
        # ответа ни от того, ни от другого нельзя: молчание такого интерфейса
        # означало бы вечную ошибку трафика на исправном узле.
        if endpoint.state in (EndpointState.DRAFT, EndpointState.RETIRED):
            continue
        if endpoint.handle not in names:
            names.append(endpoint.handle)
    return names


def _sync_server_traffic_locked(db: OrmSession, server: Server) -> dict[str, object]:
    interfaces = server_interfaces(server)
    try:
        dumps = provisioning.dumps_over_ssh(server, interfaces)
    except Exception as exc:
        server.traffic_error = str(exc)
        server.traffic_synced_at = utcnow()
        db.commit()
        return {"server_id": server.id, "error": str(exc)}

    # Счётчики со всех интерфейсов в один словарь: публичный ключ уникален в
    # пределах узла (на этом стоит уникальный индекс по адресу), поэтому
    # склейка однозначна.
    peers: dict[str, dict] = {}
    empty: list[str] = []
    for name in interfaces:
        raw = dumps.get(name, "")
        if not raw.strip():
            empty.append(name)
            continue
        peers.update(_parse_dump(raw))
    now = utcnow()
    updated = 0
    added_bytes = 0

    keys = list(
        db.scalars(
            select(UserKey).where(UserKey.server_id == server.id, UserKey.revoked_at.is_(None))
        )
    )
    for key in keys:
        peer = peers.get(key.public_key or "")
        if peer is None:
            continue

        rx, tx = peer["rx"], peer["tx"]
        # Счётчик уехал вниз — интерфейс перезапускали. Считаем текущее
        # значение приростом с нуля, а не отрицательной разницей.
        delta_rx = rx - key.rx_bytes if rx >= key.rx_bytes else rx
        delta_tx = tx - key.tx_bytes if tx >= key.tx_bytes else tx
        delta = max(0, delta_rx + delta_tx)

        key.rx_bytes = rx
        key.tx_bytes = tx
        key.traffic_synced_at = now
        if peer["handshake"] > 0:
            key.last_handshake_at = dt.datetime.utcfromtimestamp(peer["handshake"])

        if delta > 0:
            # Атомарный инкремент на уровне SQL, а не read-modify-write по
            # ORM-объекту: замок сериализует обход узла, но расход трогает и
            # сброс при продлении из другой сессии — пусть база складывает
            # сама, чтобы значение не затёрлось прочитанным до сброса.
            #
            # synchronize_session="fetch": обновлённое значение подтягивается
            # обратно в объект сессии. Без этого enforce_access, идущий тем же
            # заходом (_sync_once), видел бы прежний расход и не отключил бы
            # исчерпавшего трафик до следующего цикла.
            db.execute(
                update(User)
                .where(User.id == key.user_id)
                .values(traffic_used_bytes=User.traffic_used_bytes + delta)
                .execution_options(synchronize_session="fetch")
            )
            db.add(
                TrafficSample(
                    user_id=key.user_id,
                    server_id=server.id,
                    delta_bytes=delta,
                    rx_bytes=rx,
                    tx_bytes=tx,
                    sampled_at=now,
                )
            )
            added_bytes += delta
        updated += 1

    server.traffic_synced_at = now
    # Молчащий интерфейс — не «всё хорошо». Раньше здесь стояло безусловное
    # обнуление ошибки, и упавший awgN был бы невидим: счётчики его пиров
    # просто перестали бы расти.
    server.traffic_error = (
        None if not empty else "не отвечают интерфейсы: " + ", ".join(empty)
    )
    db.commit()
    return {
        "server_id": server.id,
        "name": server.name,
        "peers": updated,
        "added_bytes": added_bytes,
        "silent_interfaces": empty,
    }


def sync_all_traffic(db: OrmSession) -> list[dict[str, object]]:
    """Обходит все включённые серверы со своей генерацией ключей."""
    servers = list(
        db.scalars(
            select(Server).where(
                Server.is_active.is_(True), Server.provisioning == Provisioning.SSH
            )
        )
    )
    out = []
    for server in servers:
        out.append(sync_server_traffic(db, server))
        # Счётчики второго протокола — отдельным заходом и ВНЕ замка на сервер:
        # он не реентрантный, а посчитать одну дельту дважды это ровно тот баг,
        # который им и лечили.
        from . import xray

        try:
            # Сначала досылаем то, что не доехало (отзыв мог не записаться при
            # недоступном узле), потом снимаем счётчики. Порядок важен: иначе
            # отозванный доступ прожил бы на узле лишний цикл.
            xray.sync_pending(db, server)
            out.append(xray.sync_traffic(db, server))
        except Exception as exc:  # noqa: BLE001 — обход не должен падать целиком
            log.warning("узел %s: обход VLESS не удался: %s", server.name, exc)
    return out


def reconcile_peers(db: OrmSession, server: Server) -> list[str]:
    """
    Снимает с узла пиров, которым в базе не соответствует живой ключ.

    Нужна потому, что «доступ закрыт в панели» и «пир снят с узла» — два
    разных факта, и разойтись они могут по-настоящему: узел не ответил в
    момент отзыва, панель падала между добавлением пира и записью в базу,
    ключ перевыпустили и старый остался. Каждый такой пир — работающий
    доступ, которого никто не видит и никто не отзовёт.

    Проверка идёт от узла к базе: берём то, что реально настроено на
    сервере, и оставляем только известное. Обратное направление разбирает
    `ensure_keys`.

    Возвращает публичные ключи снятых пиров.
    """
    if server.provisioning != Provisioning.SSH:
        return []

    interfaces = server_interfaces(server)
    try:
        dumps = provisioning.dumps_over_ssh(server, interfaces)
    except Exception:
        return []

    def live_placement() -> dict[str, str | None]:
        """
        Публичный ключ → имя интерфейса, где он ДОЛЖЕН быть.

        `None` в значении — «подходит любой»: так трактуются ключи, у которых
        точка входа не проставлена. Это строки старше фазы 2, и на боевом узле
        их два десятка. Считать их чужими и снимать — значит одним проходом
        обхода лишить VPN всех действующих клиентов.

        Отдельная сессия на каждый снимок: с одной и той же коммит другой
        сессии не виден, пока текущая не завершит свою транзакцию, — а нам
        нужно именно свежее состояние базы между двумя чтениями.
        """
        from ..db import SessionLocal
        from ..models import NodeEndpoint

        with SessionLocal() as snapshot:
            handles = {
                row[0]: row[1]
                for row in snapshot.execute(
                    select(NodeEndpoint.id, NodeEndpoint.handle).where(
                        NodeEndpoint.server_id == server.id
                    )
                ).all()
            }
            placement: dict[str, str | None] = {}
            for key in snapshot.scalars(
                select(UserKey).where(
                    UserKey.server_id == server.id, UserKey.revoked_at.is_(None)
                )
            ):
                if not key.public_key:
                    continue
                # Неизвестная точка входа тоже даёт None: строка ссылается на
                # запись, которой уже нет, и снимать по такому признаку нельзя.
                placement[key.public_key] = handles.get(key.endpoint_id)
            return placement

    known = live_placement()

    def _is_suspect(interface: str, public_key: str) -> bool:
        if public_key not in known:
            return True  # в базе живого ключа нет вовсе
        expected = known[public_key]
        # None — «подходит любой интерфейс» (ключ старше фазы 2).
        return expected is not None and expected != interface

    suspects = [
        (name, pk)
        for name in interfaces
        for pk in _parse_dump(dumps.get(name, ""))
        if _is_suspect(name, pk)
    ]
    if not suspects:
        return []

    # Грейс перед снятием: между `add_peer_over_ssh` и коммитом public_key в
    # issue_key есть окно, где пир на узле уже есть, а в базе его ключа ещё
    # нет. Без паузы сверка сняла бы только что выданного пира, и устройство
    # осталось бы без доступа до следующего ensure_keys. Ждём и перечитываем
    # базу: закоммиченный за это время ключ уходит из подозреваемых.
    import time as _time

    _time.sleep(RECONCILE_GRACE_SECONDS)
    known_after = live_placement()

    removed: list[str] = []
    for interface, public_key in suspects:
        expected = known_after.get(public_key, ...)
        if expected is not ...:
            # Ключ появился (или уже был) в базе. Снимаем только если он
            # закреплён за ДРУГИМ интерфейсом — это залипшая копия после
            # неудачного переезда. Пустая привязка снова означает «подходит».
            if expected is None or expected == interface:
                continue
        try:
            provisioning.remove_peer_over_ssh(server, public_key, interface=interface)
        except Exception:
            continue
        removed.append(public_key)
    return removed


def enforce_access(db: OrmSession) -> list[str]:
    """
    Снимает пиры у всех, кто прямо сейчас не имеет права на доступ.

    Причин три, и лечатся они одинаково — пир уходит с узла:

    * выбран лимит трафика,
    * кончилась подписка,
    * доступ выключен или заблокирован администратором.

    Проверка идёт по `has_access()` — тому же методу, которым API решает,
    отдавать ли человеку список серверов. Держать здесь второй набор правил
    значит однажды получить разницу между «панель считает, что доступа нет»
    и «туннель работает».

    Важно, что это делается регулярно, а не только в момент решения:
    подписка кончается сама по себе, без единого запроса от кого-либо, и
    без обхода узлов человек продолжал бы пользоваться уже поднятым
    туннелем неограниченно долго.

    Возвращает описания закрытых доступов — для журнала.
    """
    from .keys import revoke_key  # локально: иначе циклический импорт

    closed: list[str] = []
    now = utcnow()

    from . import xray

    for user in db.scalars(select(User)):
        if user.has_access(now):
            continue
        live = [k for k in user.keys if k.revoked_at is None]
        # Доступы VLESS считаем наравне с awg-ключами: человек мог не иметь ни
        # одного живого пира и при этом пользоваться вторым протоколом. Раньше
        # такой выходил из цикла на первой же строке — и продолжал ходить в
        # VPN без подписки.
        live_creds = xray.revoke_for_user(db, user.id) if not user.has_access(now) else 0
        if not live and not live_creds:
            continue

        reason = _why_no_access(user, now)
        failed = 0
        for key in live:
            try:
                revoke_key(db, key)
            except Exception:
                failed += 1
                continue
        closed.append(f"{user.public_id} ({reason})" + (f", узлов не ответило: {failed}" if failed else ""))

    return closed


def _why_no_access(user, now: dt.datetime) -> str:
    if user.is_blocked:
        return "заблокирован"
    if not user.is_active:
        return "отключён"
    if user.active_subscription(now) is None:
        return "подписка кончилась"
    if user.traffic_exhausted(now):
        return "трафик исчерпан"
    return "доступа нет"


# Прежнее имя: осталось для совместимости с внешними вызовами.
enforce_traffic_limits = enforce_access
