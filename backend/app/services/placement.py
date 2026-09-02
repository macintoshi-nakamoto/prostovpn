from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import provisioning
from ..models import EndpointKind, EndpointState, NodeEndpoint, Server, User, UserKey
from . import compat
from . import endpoints as endpoints_service
from .errors import PanelError


def awg_level_of(endpoint: NodeEndpoint) -> int:
    try:
        return int((endpoint.params or {}).get("awg_version") or 1)
    except (TypeError, ValueError):
        return 1


def is_awg2(endpoint: NodeEndpoint) -> bool:
    return awg_level_of(endpoint) >= 2


def best_endpoint(endpoints: list[NodeEndpoint], client_level: int) -> NodeEndpoint | None:
    """Самая новая из живых точек, которую клиент понимает."""
    fit = [ep for ep in endpoints if ep.is_live and ep.accepts_new and awg_level_of(ep) <= client_level]
    if not fit:
        return None
    return sorted(fit, key=lambda ep: (-awg_level_of(ep), ep.priority, ep.id))[0]

log = logging.getLogger("panel.placement")

_PICK_LOCK = threading.Lock()


def pick_endpoint(
    db: OrmSession, user: User, server: Server, device_id: str = ""
) -> NodeEndpoint | None:
    device_id = (device_id or "").strip()

    awg_endpoints = [ep for ep in server.endpoints if ep.kind == EndpointKind.AWG]
    if not awg_endpoints:
        return None

    # Какое поколение наборов понимает клиент — из контекста запроса. Ноль
    # значит «не сказал»: новые ключи — на самую старую точку, существующие
    # остаются где были.
    raw_level = compat.CLIENT_AWG_LEVEL.get()
    client_level = max(raw_level, 1)

    with _PICK_LOCK:
        existing = db.scalar(
            select(UserKey).where(
                UserKey.user_id == user.id,
                UserKey.server_id == server.id,
                UserKey.device_id == device_id,
            )
        )
        if existing is not None and existing.endpoint_id is not None:
            endpoint = db.get(NodeEndpoint, existing.endpoint_id)
            if endpoint is not None:
                best = best_endpoint(awg_endpoints, client_level)
                if best is not None and awg_level_of(best) > awg_level_of(endpoint):
                    # Клиент дорос до более нового набора, ключ ещё на старой
                    # точке — при перевыпуске уедет на новую (keys.migrate_awg).
                    return best
                if best is not None and raw_level > 0 and awg_level_of(endpoint) > client_level:
                    # Ключ на точке, которую этот клиент не понимает (той же
                    # ссылкой пользовались из более новой версии) — отдаём
                    # самую новую из понятных, перевыпуск вернёт его туда.
                    return best
                return endpoint

        if existing is not None and existing.address:
            legacy = next(
                (ep for ep in awg_endpoints if ep.handle == provisioning.INTERFACE), None
            )
            return legacy

        live = [ep for ep in awg_endpoints if ep.is_live]
        if not live:
            raise PanelError("на узле нет работающих точек входа")
        # Новый ключ: самое новое поколение, которое клиент понимает; более
        # новое давать нельзя — старый движок такой конфиг отвергнет.
        understood = [ep for ep in live if awg_level_of(ep) <= client_level]
        if understood:
            top = max(awg_level_of(ep) for ep in understood)
            live = [ep for ep in understood if awg_level_of(ep) == top]

        siblings = db.scalars(
            select(UserKey.endpoint_id).where(
                UserKey.user_id == user.id,
                UserKey.server_id == server.id,
                UserKey.endpoint_id.is_not(None),
            )
        )
        sibling_ids = {value for value in siblings if value is not None}
        for endpoint in live:
            if endpoint.id in sibling_ids and endpoint.accepts_new:
                return endpoint

        accepting = [ep for ep in live if ep.accepts_new]
        if not accepting:
            raise PanelError("все точки входа узла закрыты для новых подключений")

        busy = endpoints_service.live_count(db, [ep.id for ep in accepting])
        ranked = sorted(
            accepting,
            key=lambda ep: (busy.get(ep.id, 0), ep.id),
        )
        for endpoint in ranked:
            if endpoint.capacity is None or busy.get(endpoint.id, 0) < endpoint.capacity:
                return endpoint

        raise PanelError(
            "на узле кончились места: все точки входа заполнены, заведите ещё одну"
        )


def capacity_report(db: OrmSession, server: Server) -> list[dict]:
    awg_endpoints = [ep for ep in server.endpoints if ep.kind == EndpointKind.AWG]
    busy = endpoints_service.live_count(db, [ep.id for ep in awg_endpoints])
    out = []
    for ep in sorted(awg_endpoints, key=lambda e: e.id):
        used = busy.get(ep.id, 0)
        out.append(
            {
                "id": ep.id,
                "handle": ep.handle,
                "state": ep.state.value if isinstance(ep.state, EndpointState) else ep.state,
                "port": ep.listen_port,
                "subnet": ep.subnet,
                "used": used,
                "capacity": ep.capacity,
            }
        )
    return out
