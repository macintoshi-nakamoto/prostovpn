"""
Серверы: добавление, включение и раздача ключей.

Добавленный сервер сразу раздаётся действующим пользователям — иначе новый
сервер увидят только те, кто зайдёт в приложение после его появления.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession, selectinload

from .. import services
from ..db import get_db
from ..models import Admin, Provisioning, Server, User
from . import mappers, schemas
from .deps import audit, current_admin

router = APIRouter(prefix="/servers", tags=["admin:servers"])


def _load(db: OrmSession, server_id: int) -> Server:
    # populate_existing — по той же причине, что и у пользователей: сессия не
    # сбрасывает объекты после коммита, и счётчик ключей остался бы прежним.
    server = db.scalar(
        select(Server)
        .where(Server.id == server_id)
        .options(selectinload(Server.keys))
        .execution_options(populate_existing=True)
    )
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сервер не найден")
    return server


def _apply(server: Server, body: schemas.ServerIn) -> None:
    server.name = body.name
    server.country = body.country
    server.country_en = body.country_en
    server.city = body.city
    server.country_code = (body.country_code or "").upper() or None
    server.host = body.host
    server.port = body.port
    server.provisioning = (
        Provisioning.SSH if body.provisioning == "ssh" else Provisioning.SHARED
    )
    server.shared_config = body.shared_config
    server.ssh_host = body.ssh_host or body.host
    server.ssh_port = body.ssh_port
    server.ssh_user = body.ssh_user
    # Пустая строка приходит из формы, когда поле не трогали, — не затираем
    # уже сохранённый доступ.
    if body.ssh_password:
        server.ssh_password = body.ssh_password
    if body.ssh_key:
        server.ssh_key = body.ssh_key
    server.awg_template = body.awg_template
    server.is_active = body.is_active
    server.sort_order = body.sort_order


@router.get("", response_model=list[schemas.ServerOut])
def list_servers(
    db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> list[schemas.ServerOut]:
    rows = db.scalars(
        select(Server).options(selectinload(Server.keys)).order_by(Server.sort_order, Server.id)
    )
    return [mappers.server_out(db, s) for s in rows]


@router.post("", response_model=schemas.ServerCreated, status_code=status.HTTP_201_CREATED)
def create_server(
    body: schemas.ServerIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.ServerCreated:
    if body.provisioning == "ssh" and not body.awg_template:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "для своей генерации нужен шаблон конфига с {private_key} и {address}",
        )
    if body.provisioning == "shared" and not body.shared_config:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "для общего ключа нужен сам ключ")

    server = Server(name=body.name, host=body.host)
    _apply(server, body)
    db.add(server)
    db.commit()
    db.refresh(server)

    warnings: list[str] = []
    issued = 0
    if body.issue_keys and server.is_active:
        # Ключи выдаём только тем, у кого есть доступ: заблокированному или
        # неоплаченному пир на новом сервере не нужен.
        users = db.scalars(select(User).options(selectinload(User.keys), selectinload(User.subscriptions)))
        for user in users:
            if not user.has_access():
                continue
            problems = services.ensure_keys(db, user)
            warnings += problems
            if not problems:
                issued += 1

    audit(db, admin, "server.create", server.name, f"выдано ключей: {issued}")
    return schemas.ServerCreated(
        server=mappers.server_out(db, _load(db, server.id)),
        issued=issued,
        # Один и тот же недоступный сервер повторится в каждом пользователе —
        # показываем список без повторов.
        warnings=sorted(set(warnings)),
    )


@router.put("/{server_id}", response_model=schemas.ServerOut)
def update_server(
    server_id: int,
    body: schemas.ServerIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.ServerOut:
    server = _load(db, server_id)
    _apply(server, body)
    db.commit()
    audit(db, admin, "server.update", server.name)
    return mappers.server_out(db, _load(db, server_id))


@router.post("/{server_id}/toggle", response_model=schemas.ServerOut)
def toggle_server(
    server_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.ServerOut:
    server = _load(db, server_id)
    server.is_active = not server.is_active
    db.commit()
    audit(db, admin, "server.toggle", server.name, "включён" if server.is_active else "выключен")
    return mappers.server_out(db, _load(db, server_id))


@router.post("/{server_id}/sync-traffic")
def sync_traffic(
    server_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> dict[str, object]:
    """Снять счётчики пиров прямо сейчас, не дожидаясь расписания."""
    server = _load(db, server_id)
    result = services.sync_server_traffic(db, server)
    audit(db, admin, "server.sync_traffic", server.name)
    return result


@router.delete("/{server_id}", response_model=schemas.ActionResult)
def delete_server(
    server_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.ActionResult:
    server = _load(db, server_id)
    name = server.name
    db.delete(server)
    db.commit()
    audit(db, admin, "server.delete", name)
    return schemas.ActionResult(ok=True)
