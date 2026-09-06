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

INTERFACE = "awg0"

RECONCILE_GRACE_SECONDS = 3


_PEER_FIELDS = 8


def _parse_dump(text: str) -> dict[str, dict[str, int]]:
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
            # RLock: обход по SSH берёт замок сам и затем зовёт apply_dumps,
            # который берёт его ещё раз — так же, как снимок агента.
            lock = threading.RLock()
            _server_locks[server_id] = lock
        return lock


def sync_server_traffic(db: OrmSession, server: Server) -> dict[str, object]:
    if server.provisioning != Provisioning.SSH:
        return {"server_id": server.id, "skipped": "общий ключ — счётчиков по людям нет"}

    with _lock_for_server(server.id):
        return _sync_server_traffic_locked(db, server)


def server_interfaces(server: Server) -> list[str]:
    from ..models import EndpointKind

    names = [INTERFACE]
    for endpoint in server.endpoints:
        if endpoint.kind != EndpointKind.AWG:
            continue
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
        now = utcnow()
        server.traffic_error = str(exc)
        server.traffic_synced_at = now
        # Узел не ответил по SSH. Момент первого отказа не перетираем:
        # по нему считается, сколько он уже лежит.
        if server.down_since is None:
            server.down_since = now
        db.commit()
        return {"server_id": server.id, "error": str(exc)}
    return apply_dumps(db, server, dumps, interfaces)


def apply_dumps(
    db: OrmSession,
    server: Server,
    dumps: dict[str, str],
    interfaces: list[str] | None = None,
) -> dict[str, object]:
    """
    Зачисляет счётчики пиров из выдач `awg show <if> dump` — откуда бы они ни
    пришли: обход снял их по SSH или узел прислал в снимке агента. Счётчики
    у awg абсолютные, поэтому источник можно менять на ходу: дельта всегда
    считается от того, что лежит в базе, и дважды один байт не зачислится.

    Узел, приславший выдачу, жив — здесь же снимается отметка «лежит».
    """
    interfaces = interfaces or server_interfaces(server)
    with _lock_for_server(server.id):
        return _apply_dumps_locked(db, server, dumps, interfaces)


def _apply_dumps_locked(
    db: OrmSession, server: Server, dumps: dict[str, str], interfaces: list[str]
) -> dict[str, object]:
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
        handshake_at = (
            dt.datetime.utcfromtimestamp(peer["handshake"]) if peer["handshake"] > 0 else None
        )
        if rx == key.rx_bytes and tx == key.tx_bytes:
            # Ничего не изменилось — в базу не пишем: агент шлёт снимки
            # каждые 15 секунд, а ключей на узле сотни, и переписывать все
            # строки четыре раза в минуту ради тех же чисел незачем.
            if handshake_at is not None and key.last_handshake_at != handshake_at:
                key.last_handshake_at = handshake_at
            updated += 1
            continue
        delta_rx = rx - key.rx_bytes if rx >= key.rx_bytes else rx
        delta_tx = tx - key.tx_bytes if tx >= key.tx_bytes else tx
        delta = max(0, delta_rx + delta_tx)

        key.rx_bytes = rx
        key.tx_bytes = tx
        key.traffic_synced_at = now
        if handshake_at is not None:
            key.last_handshake_at = handshake_at

        if delta > 0:
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
    server.traffic_error = (
        None if not empty else "не отвечают интерфейсы: " + ", ".join(empty)
    )
    # Узел ответил. Молчащий интерфейс — повод для предупреждения, но не
    # для «узел лежит»: остальные точки на нём продолжают работать.
    server.last_ok_at = now
    server.down_since = None
    db.commit()
    return {
        "server_id": server.id,
        "name": server.name,
        "peers": updated,
        "added_bytes": added_bytes,
        "silent_interfaces": empty,
    }


def sweep_server(db: OrmSession, server: Server) -> list[dict[str, object]]:
    """
    Обход одного узла. Где стоит агент и снимок свежий, по SSH за счётчиками
    не ходим: их уже зачислил снимок (services/agent.py). SSH остаётся на
    случай, когда агент замолчал, — тогда обход возвращается сам, и «узел
    лежит» по-прежнему означает «не ответил ни агент, ни SSH».
    """
    from . import agent as agent_service
    from . import hy2, xray

    covered = agent_service.covered(server)
    out: list[dict[str, object]] = []
    if "awg" in covered:
        out.append({"server_id": server.id, "name": server.name, "skipped": "по снимку агента"})
    else:
        out.append(sync_server_traffic(db, server))

    try:
        # Отложенные конфиги xray по-прежнему уезжают по SSH: агент пока
        # только читает узел.
        xray.sync_pending(db, server)
        if "xray" not in covered:
            out.append(xray.sync_traffic(db, server))
    except Exception as exc:
        log.warning("узел %s: обход VLESS не удался: %s", server.name, exc)

    try:
        if "hy2" not in covered:
            out.append(hy2.sync_traffic(db, server))
    except Exception as exc:
        log.warning("узел %s: обход Hysteria2 не удался: %s", server.name, exc)
    return out


def sync_all_traffic(db: OrmSession) -> list[dict[str, object]]:
    servers = list(
        db.scalars(
            select(Server).where(
                Server.is_active.is_(True), Server.provisioning == Provisioning.SSH
            )
        )
    )
    out = []
    for server in servers:
        out.extend(sweep_server(db, server))
    return out


def reconcile_peers(
    db: OrmSession, server: Server, dumps: dict[str, str] | None = None
) -> list[str]:
    """
    Снимает с узла пиры, которых нет в базе. Выдачи `awg show dump` можно
    отдать готовыми (из снимка агента) — тогда SSH нужен только на само
    удаление, а оно случается редко.
    """
    if server.provisioning != Provisioning.SSH:
        return []

    interfaces = server_interfaces(server)
    if dumps is None:
        try:
            dumps = provisioning.dumps_over_ssh(server, interfaces)
        except Exception:
            return []

    def live_placement() -> dict[str, str | None]:
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
                placement[key.public_key] = handles.get(key.endpoint_id)
            return placement

    known = live_placement()

    def _is_suspect(interface: str, public_key: str) -> bool:
        if public_key not in known:
            return True
        expected = known[public_key]
        return expected is not None and expected != interface

    suspects = [
        (name, pk)
        for name in interfaces
        for pk in _parse_dump(dumps.get(name, ""))
        if _is_suspect(name, pk)
    ]
    if not suspects:
        return []

    import time as _time

    _time.sleep(RECONCILE_GRACE_SECONDS)
    known_after = live_placement()

    removed: list[str] = []
    for interface, public_key in suspects:
        expected = known_after.get(public_key, ...)
        if expected is not ...:
            if expected is None or expected == interface:
                continue
        try:
            provisioning.remove_peer_over_ssh(server, public_key, interface=interface)
        except Exception:
            continue
        removed.append(public_key)
    return removed


def enforce_access(db: OrmSession) -> list[str]:
    from .keys import revoke_key

    closed: list[str] = []
    now = utcnow()

    from . import xray

    for user in db.scalars(select(User)):
        if user.has_access(now):
            continue
        live = [k for k in user.keys if k.revoked_at is None]
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
    if user.is_frozen:
        return "подписка на паузе"
    if user.active_subscription(now) is None:
        return "подписка кончилась"
    if user.traffic_exhausted(now):
        return "трафик исчерпан"
    return "доступа нет"


enforce_traffic_limits = enforce_access
