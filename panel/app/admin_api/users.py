"""
Пользователи: список с поиском, карточка и всё управление доступом.

Список отдаётся целиком, без страниц: панель фильтрует и сортирует на месте,
а несколько тысяч строк с уже посчитанными полями весят меньше, чем круг
запросов на каждый чих.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession, selectinload

from .. import services
from ..db import get_db
from ..models import GB, Admin, Plan, Session, User, utcnow
from . import mappers, schemas
from .deps import audit, current_admin

router = APIRouter(prefix="/users", tags=["admin:users"])


def _load(db: OrmSession, user_id: int) -> User:
    """
    Пользователь со всеми связями.

    populate_existing обязателен. Сессия живёт с expire_on_commit=False, и
    объект, уже лежащий в identity map, повторным запросом не обновляется:
    без этого ответ после продления или блокировки собирался бы из связей,
    загруженных до изменения, и показывал бы состояние «как было».
    """
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.sessions),
            selectinload(User.payments),
            selectinload(User.subscriptions),
            selectinload(User.keys),
        )
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "пользователь не найден")
    return user


def _all(db: OrmSession) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .options(
                selectinload(User.sessions),
                selectinload(User.payments),
                selectinload(User.subscriptions),
                selectinload(User.keys),
            )
            .order_by(User.created_at.desc())
        )
    )


@router.get("", response_model=list[schemas.UserRow])
def list_users(
    q: str | None = Query(default=None, description="Поиск по ID, логину, имени и контакту"),
    status_filter: str | None = Query(default=None, alias="status"),
    plan: str | None = None,
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
) -> list[schemas.UserRow]:
    now = utcnow()
    rows = [mappers.user_row(u, now) for u in _all(db)]

    if q:
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if needle in r.public_id.lower()
            or needle in r.login.lower()
            or needle in (r.name or "").lower()
            or needle in (r.contact or "").lower()
        ]
    if status_filter and status_filter != "all":
        rows = [r for r in rows if r.status == status_filter]
    if plan and plan != "all":
        rows = [r for r in rows if r.plan == plan]
    return rows


@router.post("", response_model=schemas.UserCreated, status_code=status.HTTP_201_CREATED)
def create_user(
    body: schemas.UserCreate,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.UserCreated:
    try:
        user, password, warnings = services.create_user(
            db,
            login=body.login,
            password=body.password,
            days=body.days,
            plan_code=body.plan_code,
            name=body.name,
            contact=body.contact,
            note=body.note,
            traffic_limit_bytes=body.traffic_limit_bytes,
            price=float(body.price) if body.price is not None else None,
        )
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit(db, admin, "user.create", user.public_id, f"логин {user.login}")
    return schemas.UserCreated(
        user=mappers.user_detail(_load(db, user.id)), password=password, warnings=warnings
    )


@router.get("/{user_id}", response_model=schemas.UserDetail)
def get_user(
    user_id: int, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    return mappers.user_detail(_load(db, user_id))


@router.patch("/{user_id}", response_model=schemas.UserDetail)
def update_user(
    user_id: int,
    body: schemas.UserUpdate,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.UserDetail:
    user = _load(db, user_id)
    if body.name is not None:
        user.name = body.name
    if body.contact is not None:
        user.contact = body.contact
    if body.note is not None:
        user.note = body.note
    db.commit()
    audit(db, admin, "user.update", user.public_id)
    return mappers.user_detail(_load(db, user_id))


# --- управление доступом -----------------------------------------------------


@router.post("/{user_id}/enable", response_model=schemas.UserDetail)
def enable_user(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    user = _load(db, user_id)
    services.set_user_active(db, user, True)
    audit(db, admin, "user.enable", user.public_id)
    return mappers.user_detail(_load(db, user_id))


@router.post("/{user_id}/disable", response_model=schemas.UserDetail)
def disable_user(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    """Пауза: вход остаётся, серверов не выдаём. Ключи с серверов не снимаем."""
    user = _load(db, user_id)
    services.set_user_active(db, user, False)
    audit(db, admin, "user.disable", user.public_id)
    return mappers.user_detail(_load(db, user_id))


@router.post("/{user_id}/block", response_model=schemas.UserDetail)
def block_user(
    user_id: int,
    body: schemas.BlockIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.UserDetail:
    """Бан: вход запрещён, сессии погашены, пиры сняты с серверов."""
    user = _load(db, user_id)
    problems = services.block_user(db, user, reason=body.reason)
    audit(db, admin, "user.block", user.public_id, body.reason)
    detail = mappers.user_detail(_load(db, user_id))
    if problems:
        # Пира сняли не везде — администратор должен знать, где остался доступ.
        detail.blocked_reason = (detail.blocked_reason or "") + " · " + "; ".join(problems)
    return detail


@router.post("/{user_id}/unblock", response_model=schemas.UserDetail)
def unblock_user(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    user = _load(db, user_id)
    services.unblock_user(db, user)
    audit(db, admin, "user.unblock", user.public_id)
    return mappers.user_detail(_load(db, user_id))


@router.post("/{user_id}/traffic-limit", response_model=schemas.UserDetail)
def set_traffic_limit(
    user_id: int,
    body: schemas.TrafficLimitIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.UserDetail:
    """Лимит в гигабайтах либо безлимит."""
    user = _load(db, user_id)
    limit = None if body.unlimited or body.limit_gb is None else int(body.limit_gb * GB)
    try:
        services.set_traffic_limit(db, user, limit)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "user.traffic_limit", user.public_id, "безлимит" if limit is None else f"{body.limit_gb} ГБ")
    return mappers.user_detail(_load(db, user_id))


@router.post("/{user_id}/traffic-reset", response_model=schemas.UserDetail)
def reset_traffic(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    user = _load(db, user_id)
    services.reset_traffic(db, user)
    audit(db, admin, "user.traffic_reset", user.public_id)
    return mappers.user_detail(_load(db, user_id))


@router.post("/{user_id}/extend", response_model=schemas.UserDetail)
def extend_subscription(
    user_id: int,
    body: schemas.ExtendIn,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.UserDetail:
    """
    Продление. Если пришёл тариф — берём срок и цену из него.

    Оплату регистрируем тем же действием: в жизни продление и есть платёж,
    а два отдельных шага дают расхождение между доступом и деньгами.
    """
    user = _load(db, user_id)

    plan: Plan | None = None
    if body.plan_code:
        plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
        if plan is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"тариф «{body.plan_code}» не найден")

    days = body.days or (plan.period_days if plan else 30)
    price = body.price if body.price is not None else (Decimal(str(plan.price)) if plan else None)

    try:
        sub = services.grant_subscription(
            db, user, days=days, plan=plan, price=float(price) if price is not None else None
        )
        if body.register_payment and price and price > 0:
            services.add_payment(
                db,
                amount=price,
                user=user,
                method=body.method or "панель",
                comment=f"Продление {sub.plan} на {days} дн.",
                subscription_id=sub.id,
            )
        # Новый оплаченный период — новый счёт трафика.
        services.reset_traffic(db, user)
        # Заблокированному продление ничего не даёт, а выключенного включаем:
        # человек заплатил, значит доступ должен появиться.
        if not user.is_blocked and not user.is_active:
            services.set_user_active(db, user, True)
        services.ensure_keys(db, user)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit(db, admin, "user.extend", user.public_id, f"{days} дн., {price or 0}")
    return mappers.user_detail(_load(db, user_id))


@router.post("/{user_id}/password", response_model=schemas.PasswordOut)
def reset_password(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.PasswordOut:
    user = _load(db, user_id)
    password = services.set_password(db, user)
    audit(db, admin, "user.password", user.public_id)
    return schemas.PasswordOut(password=password)


@router.delete("/{user_id}/sessions/{session_id}", response_model=schemas.ActionResult)
def kill_session(
    user_id: int,
    session_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.ActionResult:
    session = db.get(Session, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    session.revoked_at = utcnow()
    db.commit()
    audit(db, admin, "session.kill", str(session_id))
    return schemas.ActionResult(ok=True)


@router.delete("/{user_id}", response_model=schemas.ActionResult)
def delete_user(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.ActionResult:
    """Удаление с попыткой убрать пиров: иначе доступ переживёт запись в базе."""
    user = _load(db, user_id)
    public_id = user.public_id
    problems = services.block_user(db, user, reason="удаление")
    db.delete(user)
    db.commit()
    audit(db, admin, "user.delete", public_id)
    return schemas.ActionResult(ok=True, warnings=problems)
