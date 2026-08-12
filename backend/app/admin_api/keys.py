"""
Вкладка «Ключи»: какой аккаунт на каком сервере и с каким ключом.

Отдельно от пользователей и от серверов, потому что вопрос третий: не «что
у человека» и не «что на сервере», а связь между ними.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession, selectinload

from .. import services
from ..db import get_db
from ..models import Admin, User, UserKey, utcnow
from . import mappers, schemas
from .deps import audit, current_admin

router = APIRouter(prefix="/keys", tags=["admin:keys"])


@router.get("", response_model=list[schemas.KeyRow])
def list_keys(
    q: str | None = Query(default=None),
    server_id: int | None = None,
    only_active: bool = True,
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> list[schemas.KeyRow]:
    now = utcnow()
    stmt = (
        select(UserKey)
        .options(
            selectinload(UserKey.server),
            selectinload(UserKey.user).selectinload(User.subscriptions),
        )
        .order_by(UserKey.server_id, UserKey.id)
    )
    if server_id:
        stmt = stmt.where(UserKey.server_id == server_id)
    if only_active:
        stmt = stmt.where(UserKey.revoked_at.is_(None))

    rows: list[schemas.KeyRow] = []
    for key in db.scalars(stmt):
        user, server = key.user, key.server
        rows.append(
            schemas.KeyRow(
                id=key.id,
                user_id=user.id,
                public_id=user.public_id,
                login=user.login,
                name=user.name,
                user_status=mappers.user_status(user, now),
                server_id=server.id,
                server_name=server.name,
                country=server.country,
                country_code=server.country_code,
                city=server.city,
                provisioning=server.provisioning.value,
                device_id=key.device_id or "",
                address=key.address,
                public_key=key.public_key,
                rx_bytes=key.rx_bytes,
                tx_bytes=key.tx_bytes,
                last_handshake_at=key.last_handshake_at,
                created_at=key.created_at,
                revoked_at=key.revoked_at,
                is_active=key.revoked_at is None,
            )
        )

    if q:
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if needle in r.public_id.lower()
            or needle in r.login.lower()
            or needle in (r.name or "").lower()
            or needle in r.server_name.lower()
            or needle in (r.country or "").lower()
            or needle in (r.address or "").lower()
        ]
    return rows


@router.post("/{key_id}/revoke", response_model=schemas.ActionResult)
def revoke(
    key_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.ActionResult:
    key = db.get(UserKey, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ключ не найден")
    try:
        services.revoke_key(db, key)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"сервер не ответил: {exc}") from exc
    audit(db, admin, "key.revoke", f"{key.user_id}@{key.server_id}")
    return schemas.ActionResult(ok=True)


@router.post("/reissue/{user_id}/{server_id}", response_model=schemas.ActionResult)
def reissue(
    user_id: int,
    server_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.ActionResult:
    """
    Перевыпуск: старые пиры снимаем, новые заводим.

    Нужен, когда конфиг утёк — менять его должно быть так же просто, как
    сменить пароль. Пиров у человека на сервере столько, сколько у него
    устройств, и перевыпускать надо все: утёкшим считается доступ, а не
    один телефон. Устройства получат новый конфиг при ближайшем обращении
    приложения к списку серверов.
    """
    from ..models import Server

    user = db.get(User, user_id)
    server = db.get(Server, server_id)
    if user is None or server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "пользователь или сервер не найден")

    existing = list(
        db.scalars(
            select(UserKey).where(
                UserKey.user_id == user_id,
                UserKey.server_id == server_id,
                UserKey.revoked_at.is_(None),
            )
        )
    )
    # Устройства, которым доступ положен, — плюс те, у кого уже есть ключ:
    # ключ мог остаться от устройства, которое сейчас не в сети, и молча
    # не перевыпустить именно его значит оставить утёкший конфиг рабочим.
    devices = services.known_devices(user) | {key.device_id or "" for key in existing}

    for key in existing:
        try:
            services.revoke_key(db, key)
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"старый ключ не снят: {exc}") from exc

    for device_id in sorted(devices):
        try:
            # rotate=True: здесь пара ключей меняется намеренно. При обычном
            # возвращении доступа она сохраняется, иначе конфиг, лежащий у
            # человека в приложении, превратился бы в мусор.
            services.issue_key(db, user, server, rotate=True, device_id=device_id)
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"новый ключ не создан: {exc}") from exc

    audit(db, admin, "key.reissue", f"{user.public_id}@{server.name}")
    return schemas.ActionResult(ok=True)


@router.post("/sync-traffic")
def sync_all(
    db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> list[dict[str, object]]:
    audit(db, admin, "traffic.sync_all")
    return services.sync_all_traffic(db)
