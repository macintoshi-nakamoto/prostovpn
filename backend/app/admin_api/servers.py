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
from ..models import Admin, Provisioning, Server, User, utcnow
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
    """
    Переносит форму в сервер.

    Общее правило для всего, что форма не показывает: пустое значение
    означает «не трогали», а не «сотри». Шаблон конфига, общий ключ, пароль
    и ключ SSH наружу не отдаются — иначе они разъезжались бы по каждому
    ответу со списком серверов, — и форма при редактировании присылает по
    ним пустоту. Присваивание без проверки стирало бы ровно то, на чём
    держится выдача доступа: сохранение узла ради переименования оставляло
    бы его без шаблона и без доступа по SSH.
    """
    # Что влияет на точку подключения клиента. Смена любого поднимает
    # endpoint_rev — по нему подписка отдаёт revision, и клиент видит, что
    # endpoint изменился. Для нового сервера (id ещё нет) не бампаем: он и так
    # стартует с 1. awg_template учитываем тоже: смена обфускации меняет конфиг.
    _endpoint_before = (
        server.host,
        server.port,
        server.alt_ports or "",
        server.awg_template or "",
    )

    server.name = body.name
    server.country = body.country
    server.country_en = body.country_en
    server.city = body.city
    server.city_en = body.city_en
    server.country_code = (body.country_code or "").upper() or None
    server.host = body.host
    server.port = body.port
    # Нормализуем на входе: в поле панели человек напишет и «443, 2408», и
    # «443;2408», и лишний пробел. Хранить это как набрано — значит однажды
    # молча потерять порт из-за пробела.
    server.alt_ports = ",".join(
        str(int(chunk))
        for chunk in (body.alt_ports or "").replace(";", ",").split(",")
        if chunk.strip().isdigit() and 0 < int(chunk) < 65536
    )
    server.provisioning = (
        Provisioning.SSH if body.provisioning == "ssh" else Provisioning.SHARED
    )
    server.ssh_host = body.ssh_host or server.ssh_host or body.host
    server.ssh_port = body.ssh_port
    server.ssh_user = body.ssh_user or server.ssh_user

    if body.shared_config:
        server.shared_config = body.shared_config
    if body.awg_template:
        server.awg_template = body.awg_template
    if body.ssh_password:
        server.ssh_password = body.ssh_password
    if body.ssh_key:
        server.ssh_key = body.ssh_key

    server.is_active = body.is_active
    server.sort_order = body.sort_order

    _endpoint_after = (
        server.host,
        server.port,
        server.alt_ports or "",
        server.awg_template or "",
    )
    if server.id is not None and _endpoint_before != _endpoint_after:
        server.endpoint_rev = (server.endpoint_rev or 1) + 1
        # Историческая точка входа описывает тот же интерфейс, что поля узла.
        # Без синхронизации поле «Запасные порты» в панели превратилось бы в
        # пустышку: выдача читает порты точки входа, и правка узла до клиентов
        # просто не доезжала бы — молча, без единого признака.
        from ..models import EndpointKind, NodeEndpoint
        from ..provisioning import INTERFACE

        for endpoint in server.endpoints:
            if endpoint.kind == EndpointKind.AWG and endpoint.handle == INTERFACE:
                endpoint.listen_port = server.port
                endpoint.alt_ports = server.alt_ports or ""
                endpoint.rev = (endpoint.rev or 1) + 1


def _check_usable(server: Server) -> None:
    """
    Сервер обязан уметь выдать конфиг — иначе он бесполезен и опасен.

    Проверяется итоговое состояние, а не присланная форма: при
    переключении режима нужное поле могло остаться с прошлого раза, и
    требовать прислать его заново значит заставить администратора вставлять
    шаблон при каждом переименовании узла.
    """
    if server.provisioning == Provisioning.SSH and not server.awg_template:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "для своей генерации нужен шаблон конфига с {private_key} и {address}",
        )
    if server.provisioning == Provisioning.SHARED and not server.shared_config:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "для общего ключа нужен сам ключ")


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
    server = Server(name=body.name, host=body.host)
    _apply(server, body)
    _check_usable(server)
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
    # Проверяем итог, а не форму: нужное поле могло прийти пустым, потому
    # что его не показывают, и остаться с прошлого сохранения.
    _check_usable(server)
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


@router.post("/{server_id}/check", response_model=schemas.ServerCheck)
def check_server(
    server_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.ServerCheck:
    """
    Проверить узел по-настоящему: адрес, порт, SSH, поднятый интерфейс.

    Существует потому, что «включён» и «работает» — разные вещи, а панель
    показывала только первое. Узел с адресом из документационного диапазона
    или с непо­днятым awg0 выглядел зелёным, клиент входил в приложение и
    упирался в тишину.
    """
    server = _load(db, server_id)
    report = services.check_server(server)

    server.health_ok = report.usable
    server.health_summary = report.summary
    server.health_checked_at = utcnow()
    if report.facts:
        # Данные обновляем, только если их удалось собрать: недоступный
        # сегодня узел не должен терять то, что о нём было известно вчера.
        server.facts = report.facts
    db.commit()

    audit(db, admin, "server.check", server.name, report.summary)
    return schemas.ServerCheck(
        server_id=report.server_id,
        server_name=report.server_name,
        usable=report.usable,
        summary=report.summary,
        checks=[
            schemas.CheckItem(name=c.name, ok=c.ok, detail=c.detail) for c in report.checks
        ],
    )


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
