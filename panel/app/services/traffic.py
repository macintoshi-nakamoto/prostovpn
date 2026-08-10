"""
Учёт трафика: снимаем счётчики пиров с серверов по SSH.

`awg show <iface> dump` печатает по строке на пира с абсолютными rx/tx с
момента поднятия интерфейса. Мы храним предыдущий замер и копим разницу:
после перезагрузки сервера счётчик уезжает в ноль, и абсолютное значение
дало бы отрицательный прирост либо потерю всей истории.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import provisioning
from ..models import Provisioning, Server, TrafficSample, UserKey, utcnow

# Интерфейс AmneziaWG на сервере — тот же, что использует provisioning.
INTERFACE = "awg0"


def _parse_dump(text: str) -> dict[str, dict[str, int]]:
    """
    Разбирает вывод `awg show <iface> dump`.

    Первая строка — сам интерфейс (там свой набор полей), пиры идут дальше:
    public_key, preshared_key, endpoint, allowed_ips, latest_handshake, rx, tx,
    persistent_keepalive.
    """
    peers: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        public_key, _psk, _endpoint, _allowed, handshake, rx, tx = parts[:7]
        try:
            peers[public_key.strip()] = {
                "handshake": int(handshake),
                "rx": int(rx),
                "tx": int(tx),
            }
        except ValueError:
            continue
    return peers


def sync_server_traffic(db: OrmSession, server: Server) -> dict[str, object]:
    """
    Обновляет расход трафика по всем пирам одного сервера.

    Ошибку не поднимаем наверх, а записываем в сам сервер: один недоступный
    сервер не должен ронять обход остальных.
    """
    if server.provisioning != Provisioning.SSH:
        return {"server_id": server.id, "skipped": "общий ключ — счётчиков по людям нет"}

    try:
        raw = provisioning.run_over_ssh(server, f"awg show {INTERFACE} dump")
    except Exception as exc:
        server.traffic_error = str(exc)
        server.traffic_synced_at = utcnow()
        db.commit()
        return {"server_id": server.id, "error": str(exc)}

    peers = _parse_dump(raw)
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
            key.user.traffic_used_bytes += delta
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
    server.traffic_error = None
    db.commit()
    return {
        "server_id": server.id,
        "name": server.name,
        "peers": updated,
        "added_bytes": added_bytes,
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
    return [sync_server_traffic(db, server) for server in servers]


def enforce_traffic_limits(db: OrmSession) -> list[int]:
    """
    Снимает пиров у тех, кто выбрал лимит.

    Возвращает id пользователей, у которых доступ закрыли, — их видно в
    журнале и в панели.
    """
    from .keys import revoke_key  # локально: иначе циклический импорт

    from ..models import User

    hit: list[int] = []
    now = utcnow()
    for user in db.scalars(select(User).where(User.is_blocked.is_(False))):
        if not user.traffic_exhausted(now):
            continue
        live = [k for k in user.keys if k.revoked_at is None]
        if not live:
            continue
        for key in live:
            try:
                revoke_key(db, key)
            except Exception:
                continue
        hit.append(user.id)
    return hit
