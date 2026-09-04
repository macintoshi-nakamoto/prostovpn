"""
Hysteria2 на узлах: учёт трафика и отключение отозванных.

Пользователей у Hysteria2 нет — доступ на каждое соединение решает панель
(`hy2_api.auth`) по UUID VLESS-учётки. Но живое соединение переживает
отзыв: узел спрашивает панель лишь при подключении. Поэтому при отзыве
учётки её же «id» (label учётки) выкидывается через API узла. Там же
снимаются счётчики трафика — по тем же label, что и у xray.

API — `trafficStats` в /opt/prosto-hy2/config.yaml, слушает только
localhost узла, секрет лежит рядом в stats.secret; ходим через SSH.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select, update as sql_update
from sqlalchemy.orm import Session as OrmSession

from .. import provisioning
from ..models import (
    EndpointKind,
    EndpointState,
    NodeEndpoint,
    Server,
    TrafficSample,
    User,
    UserEndpointCred,
    utcnow,
)

log = logging.getLogger("panel.hy2")

HY2_DIR = "/opt/prosto-hy2"
SECRET_FILE = f"{HY2_DIR}/stats.secret"
DEFAULT_STATS_PORT = 10086


def endpoint_for(db: OrmSession, server: Server) -> NodeEndpoint | None:
    """VLESS-точка узла, у которой включён Hysteria2 (params.hy2)."""
    for endpoint in db.scalars(
        select(NodeEndpoint)
        .where(
            NodeEndpoint.server_id == server.id,
            NodeEndpoint.kind == EndpointKind.VLESS,
            NodeEndpoint.state != EndpointState.RETIRED,
        )
        .order_by(NodeEndpoint.priority, NodeEndpoint.id)
    ):
        if (endpoint.params or {}).get("hy2", {}).get("port"):
            return endpoint
    return None


def _api(server: Server, endpoint: NodeEndpoint, path: str, body: list | None = None) -> str:
    port = (endpoint.params or {}).get("hy2", {}).get("stats_port") or DEFAULT_STATS_PORT
    command = f'curl -s -m 8 -H "Authorization: $(cat {SECRET_FILE})"'
    if body is not None:
        payload = provisioning._quote(json.dumps(body, ensure_ascii=False))
        command += f" -X POST -H 'Content-Type: application/json' -d {payload}"
    command += f" http://127.0.0.1:{int(port)}{path}"
    return provisioning.run_over_ssh(server, command)


def kick(server: Server, labels: list[str]) -> bool:
    """Рвёт живые соединения по label учётки. Пустой список — ничего не делает."""
    labels = [label for label in labels if label]
    if not labels:
        return True
    from ..db import SessionLocal

    with SessionLocal() as db:
        endpoint = endpoint_for(db, db.get(Server, server.id) or server)
    if endpoint is None:
        return True
    try:
        _api(server, endpoint, "/kick", body=labels)
    except Exception as exc:
        log.warning("узел %s: Hysteria2 не отключил %d учёток: %s", server.name, len(labels), exc)
        return False
    return True


def sync_traffic(db: OrmSession, server: Server) -> dict[str, object]:
    """
    Снимает и обнуляет счётчики Hysteria2 и зачисляет их людям.

    Счётчики xray абсолютные, а здесь — дельты с прошлого снятия
    (`clear=1`), поэтому rx/tx самой учётки не трогаем: они принадлежат
    xray, и дельта там считается разницей. Hysteria2 добавляет только
    в общий счётчик человека и в выборку трафика.
    """
    endpoint = endpoint_for(db, server)
    if endpoint is None:
        return {"server_id": server.id, "skipped": "Hysteria2 не включён"}

    try:
        raw = _api(server, endpoint, "/traffic?clear=1")
        data = json.loads(raw or "{}")
    except Exception as exc:
        log.warning("узел %s: счётчики Hysteria2 не сняты: %s", server.name, exc)
        return {"server_id": server.id, "error": str(exc)}
    if not isinstance(data, dict):
        data = {}

    # Кто подключён прямо сейчас: /online отдаёт label → число соединений.
    # Отдельно от трафика: сессия QUIC может висеть без единого байта, и
    # человек при этом подключён — раньше он через три минуты «пропадал».
    online: set[str] = set()
    try:
        raw_online = _api(server, endpoint, "/online")
        for label, count in (json.loads(raw_online or "{}") or {}).items():
            if int(count or 0) > 0:
                online.add(str(label))
    except Exception as exc:
        log.warning("узел %s: онлайн Hysteria2 не снят: %s", server.name, exc)

    now = utcnow()
    live_now = 0
    if online:
        for cred in db.scalars(
            select(UserEndpointCred).where(
                UserEndpointCred.server_id == server.id,
                UserEndpointCred.revoked_at.is_(None),
                UserEndpointCred.label.in_(sorted(online)),
            )
        ):
            cred.last_seen_at = now
            live_now += 1

    if not data:
        db.commit()
        return {"server_id": server.id, "peers": 0, "added_bytes": 0, "online": live_now}

    updated = 0
    added_bytes = 0
    for label, pair in data.items():
        if not isinstance(pair, dict):
            continue
        try:
            rx = int(pair.get("rx") or 0)
            tx = int(pair.get("tx") or 0)
        except (TypeError, ValueError):
            continue
        delta = max(0, rx + tx)
        cred = db.scalar(
            select(UserEndpointCred).where(
                UserEndpointCred.server_id == server.id,
                UserEndpointCred.label == label,
            )
        )
        if cred is None:
            continue
        updated += 1
        if delta <= 0:
            continue
        cred.last_seen_at = now
        db.execute(
            sql_update(User)
            .where(User.id == cred.user_id)
            .values(traffic_used_bytes=User.traffic_used_bytes + delta)
            .execution_options(synchronize_session="fetch")
        )
        db.add(
            TrafficSample(
                user_id=cred.user_id,
                server_id=server.id,
                delta_bytes=delta,
                rx_bytes=rx,
                tx_bytes=tx,
                sampled_at=now,
            )
        )
        added_bytes += delta

    db.commit()
    return {
        "server_id": server.id,
        "peers": updated,
        "added_bytes": added_bytes,
        "online": live_now,
    }
