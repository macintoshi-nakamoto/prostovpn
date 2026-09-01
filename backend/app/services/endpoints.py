from __future__ import annotations

import ipaddress
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from .. import obfuscation as obf
from .. import provisioning
from ..models import (
    EndpointKind,
    EndpointState,
    NodeEndpoint,
    Server,
    UserKey,
    utcnow,
)
from .errors import PanelError

log = logging.getLogger("panel.endpoints")

SUBNET_TEMPLATE = "10.8.{octet}.0/24"
BASE_PORT = 51820


def _suggest_slot(db: OrmSession, server: Server) -> tuple[str, int, str]:
    taken_handles = {ep.handle for ep in server.endpoints}
    taken_ports = {ep.listen_port for ep in server.endpoints} | {server.port}
    for ep in server.endpoints:
        taken_ports |= set(ep.alt_port_list())
    taken_ports |= set(server.alt_port_list())
    taken_subnets = {ep.subnet for ep in server.endpoints if ep.subnet}

    for index in range(0, 100):
        handle = f"awg{index}"
        port = BASE_PORT + index
        subnet = SUBNET_TEMPLATE.format(octet=index + 1)
        if handle in taken_handles or port in taken_ports or subnet in taken_subnets:
            continue
        return handle, port, subnet
    raise PanelError("на узле не осталось свободных слотов под интерфейс")


def create_awg_endpoint(
    db: OrmSession,
    server: Server,
    *,
    handle: str | None = None,
    listen_port: int | None = None,
    subnet: str | None = None,
    alt_ports: str = "",
    capacity: int | None = None,
    note: str | None = None,
    obfuscation_set: obf.ObfuscationSet | None = None,
) -> NodeEndpoint:
    suggested_handle, suggested_port, suggested_subnet = _suggest_slot(db, server)
    handle = provisioning.iface_name(handle or suggested_handle)
    listen_port = int(listen_port or suggested_port)
    subnet = subnet or suggested_subnet

    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as exc:
        raise PanelError(f"неверная подсеть: {exc}") from exc
    if not (0 < listen_port < 65536):
        raise PanelError("порт вне диапазона")

    spare = _clean_ports(alt_ports, listen_port)
    wanted = {listen_port} | {int(p) for p in spare.split(",") if p}

    # Заняты порты только своего транспорта: заводим AWG, то есть UDP, а
    # VLESS Reality сидит на TCP. Пока считали общим списком, 443/UDP —
    # самый живучий порт на мобильных сетях, потому что неотличим от QUIC —
    # был недоступен только из-за того, что 443/TCP занят Reality. На узле
    # они не конфликтуют: xray слушает TCP, iptables заворачивает UDP на awg.
    taken: dict[int, str] = {}
    if handle != provisioning.INTERFACE:
        taken[server.port] = "узла"
        for port in server.alt_port_list():
            taken[port] = "узла"
    for ep in server.endpoints:
        if ep.handle == handle:
            raise PanelError(f"точка входа {handle} на этом узле уже есть")
        if (ep.transport or "udp") == "udp":
            taken[ep.listen_port] = ep.handle
            for port in ep.alt_port_list():
                taken[port] = ep.handle
        if ep.subnet and ipaddress.ip_network(ep.subnet, strict=False).overlaps(network):
            raise PanelError(f"подсеть {subnet} пересекается с {ep.subnet}")

    for port in sorted(wanted):
        owner = taken.get(port)
        if owner is not None:
            raise PanelError(f"порт {port} уже занят по UDP ({owner})")

    values = obfuscation_set or obf.generate()
    endpoint = NodeEndpoint(
        server_id=server.id,
        kind=EndpointKind.AWG,
        transport="udp",
        handle=handle,
        listen_port=listen_port,
        alt_ports=spare,
        subnet=str(network),
        params={
            **values.as_dict(),
            # Первый пакет от клиента выглядит как QUIC Initial (AWG 1.5);
            # выдаётся только приложениям, которые его понимают.
            "i1": obf.QUIC_INITIAL,
            "dns": "1.1.1.1, 1.0.0.1",
            "mtu": 1280,
            "allowed_ips": "0.0.0.0/0, ::/0",
            "keepalive": 25,
            "server_public_key": "",
        },
        priority=0,
        capacity=capacity,
        state=EndpointState.DRAFT,
        note=note,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    log.info("заведена точка входа %s (порт %s, подсеть %s)", handle, listen_port, subnet)
    return endpoint


def _clean_ports(value: str, listen_port: int) -> str:
    out: list[int] = []
    for chunk in (value or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk.isdigit():
            continue
        port = int(chunk)
        if 0 < port < 65536 and port != listen_port and port not in out:
            out.append(port)
    return ",".join(str(p) for p in out)


def apply_awg_endpoint(db: OrmSession, endpoint: NodeEndpoint) -> NodeEndpoint:
    if endpoint.kind != EndpointKind.AWG:
        raise PanelError("применять на узле умеем только awg-точки входа")
    server = endpoint.server
    result = provisioning.create_awg_interface(server, endpoint)

    params = dict(endpoint.params or {})
    params["server_public_key"] = result["public_key"]
    endpoint.params = params
    endpoint.state = EndpointState.ACTIVE
    endpoint.rev = (endpoint.rev or 1) + 1
    db.commit()
    db.refresh(endpoint)
    log.info(
        "точка входа %s применена на узле %s (%s)",
        endpoint.handle,
        server.name,
        "уже существовала" if result.get("existed") else "создана",
    )
    return endpoint


def live_count(db: OrmSession, endpoint_ids: list[int]) -> dict[int, int]:
    if not endpoint_ids:
        return {}
    from sqlalchemy import func

    rows = db.execute(
        select(UserKey.endpoint_id, func.count(UserKey.id))
        .where(UserKey.endpoint_id.in_(endpoint_ids), UserKey.address.is_not(None))
        .group_by(UserKey.endpoint_id)
    ).all()
    return {row[0]: row[1] for row in rows}


def set_state(db: OrmSession, endpoint: NodeEndpoint, state: EndpointState) -> NodeEndpoint:
    if state in (EndpointState.ACTIVE, EndpointState.DRAINING):
        if endpoint.kind == EndpointKind.AWG and not (endpoint.params or {}).get(
            "server_public_key"
        ):
            raise PanelError(
                "точка входа ещё не поднята на узле — сначала «Поднять на узле»"
            )

    if state == EndpointState.RETIRED:
        if endpoint.kind == EndpointKind.AWG:
            busy = live_count(db, [endpoint.id]).get(endpoint.id, 0)
            if busy:
                raise PanelError(
                    f"на точке входа ещё {busy} доступов — сначала переведите её в «слив» "
                    f"и дождитесь переезда"
                )
        else:
            from ..models import UserEndpointCred

            revoked = db.execute(
                update(UserEndpointCred)
                .where(
                    UserEndpointCred.endpoint_id == endpoint.id,
                    UserEndpointCred.revoked_at.is_(None),
                )
                .values(revoked_at=utcnow())
            ).rowcount
            if revoked:
                log.info("точка входа %s: снято доступов %d", endpoint.handle, revoked)
    endpoint.state = state
    endpoint.rev = (endpoint.rev or 1) + 1
    db.commit()
    db.refresh(endpoint)

    if endpoint.kind == EndpointKind.VLESS:
        from . import xray

        xray.push_to_node(db, endpoint.server)
    return endpoint


def endpoint_for_key(db: OrmSession, key: UserKey) -> NodeEndpoint | None:
    if key.endpoint_id is None:
        return None
    return db.get(NodeEndpoint, key.endpoint_id)


def interface_of(db: OrmSession, key: UserKey) -> str:
    endpoint = endpoint_for_key(db, key)
    return endpoint.handle if endpoint is not None else provisioning.INTERFACE
