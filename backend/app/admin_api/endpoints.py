from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import services
from ..db import get_db
from ..models import Admin, EndpointKind, EndpointState, NodeEndpoint, Server
from ..services.endpoints import apply_awg_endpoint, create_awg_endpoint, live_count, set_state
from ..services.errors import PanelError
from .deps import audit, current_admin
from .schemas import Schema

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


class EndpointOut(Schema):
    id: int
    server_id: int
    server_name: str
    kind: str
    transport: str
    handle: str
    listen_port: int
    alt_ports: str
    subnet: str | None
    state: str
    priority: int
    capacity: int | None
    used: int
    rev: int
    note: str | None
    obfuscation: dict | None


class EndpointIn(BaseModel):
    server_id: int
    handle: str | None = Field(default=None, max_length=32)
    listen_port: int | None = None
    subnet: str | None = Field(default=None, max_length=32)
    alt_ports: str = ""
    capacity: int | None = None
    note: str | None = None


class StateIn(BaseModel):
    state: str


class VlessIn(BaseModel):
    server_id: int
    listen_port: int
    server_names: list[str]
    dest: str | None = None
    handle: str | None = Field(default=None, max_length=32)
    capacity: int | None = None
    note: str | None = None


def _out(db: OrmSession, endpoint: NodeEndpoint, used: int | None = None) -> EndpointOut:
    obfuscation = endpoint.obfuscation()
    if used is None:
        used = live_count(db, [endpoint.id]).get(endpoint.id, 0)
    return EndpointOut(
        id=endpoint.id,
        server_id=endpoint.server_id,
        server_name=endpoint.server.name,
        kind=endpoint.kind.value if isinstance(endpoint.kind, EndpointKind) else endpoint.kind,
        transport=endpoint.transport,
        handle=endpoint.handle,
        listen_port=endpoint.listen_port,
        alt_ports=endpoint.alt_ports or "",
        subnet=endpoint.subnet,
        state=endpoint.state.value if isinstance(endpoint.state, EndpointState) else endpoint.state,
        priority=endpoint.priority,
        capacity=endpoint.capacity,
        used=used,
        rev=endpoint.rev,
        note=endpoint.note,
        obfuscation=obfuscation.as_dict() if obfuscation else None,
    )


@router.get("", response_model=list[EndpointOut])
def list_endpoints(
    server_id: int | None = None,
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> list[EndpointOut]:
    query = select(NodeEndpoint).order_by(NodeEndpoint.server_id, NodeEndpoint.id)
    if server_id is not None:
        query = query.where(NodeEndpoint.server_id == server_id)
    rows = list(db.scalars(query))
    busy = live_count(db, [row.id for row in rows])
    return [_out(db, row, busy.get(row.id, 0)) for row in rows]


@router.post("", response_model=EndpointOut, status_code=status.HTTP_201_CREATED)
def create_endpoint(
    body: EndpointIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> EndpointOut:
    server = db.get(Server, body.server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сервер не найден")
    try:
        endpoint = create_awg_endpoint(
            db,
            server,
            handle=body.handle,
            listen_port=body.listen_port,
            subnet=body.subnet,
            alt_ports=body.alt_ports,
            capacity=body.capacity,
            note=body.note,
        )
    except (PanelError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "endpoint.create", server.name, endpoint.handle)
    return _out(db, endpoint)


@router.post("/{endpoint_id}/apply", response_model=EndpointOut)
def apply_endpoint(
    endpoint_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> EndpointOut:
    endpoint = db.get(NodeEndpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "точка входа не найдена")
    try:
        endpoint = apply_awg_endpoint(db, endpoint)
    except (PanelError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"узел не ответил: {exc}") from exc
    audit(db, admin, "endpoint.apply", endpoint.server.name, endpoint.handle)
    return _out(db, endpoint)


@router.post("/vless", response_model=EndpointOut, status_code=status.HTTP_201_CREATED)
def create_vless(
    body: VlessIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> EndpointOut:
    server = db.get(Server, body.server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сервер не найден")
    try:
        endpoint = services.xray.create_vless_endpoint(
            db,
            server,
            listen_port=body.listen_port,
            server_names=[n.strip() for n in body.server_names if n.strip()],
            dest=body.dest,
            handle=body.handle,
            capacity=body.capacity,
            note=body.note,
        )
    except PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"узел не ответил: {exc}") from exc
    audit(db, admin, "endpoint.create_vless", server.name, endpoint.handle)
    return _out(db, endpoint)


@router.post("/{endpoint_id}/sync", response_model=EndpointOut)
def sync_vless(
    endpoint_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> EndpointOut:
    endpoint = db.get(NodeEndpoint, endpoint_id)
    if endpoint is None or endpoint.kind != EndpointKind.VLESS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "точка входа VLESS не найдена")
    try:
        services.xray.apply_config(db, endpoint.server)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"узел не ответил: {exc}") from exc
    audit(db, admin, "endpoint.sync", endpoint.server.name, endpoint.handle)
    return _out(db, endpoint)


@router.post("/{endpoint_id}/state", response_model=EndpointOut)
def change_state(
    endpoint_id: int,
    body: StateIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> EndpointOut:
    endpoint = db.get(NodeEndpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "точка входа не найдена")
    try:
        state = EndpointState(body.state)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "неизвестное состояние") from exc
    if state == EndpointState.DRAFT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "вернуть в черновик нельзя")
    try:
        endpoint = set_state(db, endpoint, state)
    except PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "endpoint.state", endpoint.server.name, f"{endpoint.handle} → {state.value}")
    return _out(db, endpoint)
