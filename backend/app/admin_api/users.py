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
from ..models import GB, Admin, Order, Plan, Session, User, normalize_email, utcnow
from . import mappers, schemas
from .deps import audit, current_admin

router = APIRouter(prefix="/users", tags=["admin:users"])


def _orders(db: OrmSession, user: User) -> list[Order]:
    """
    История покупок клиента — и по учётке, и по почте.

    По почте тоже, и это важнее, чем кажется: заказ, который не удалось
    выдать — сумма не сошлась, вебхук не дошёл, — остался без ссылки на
    пользователя. Именно такой заказ и ищут в карточке, когда человек
    пишет «я заплатил, а доступа нет».
    """
    condition = Order.user_id == user.id
    # Почта в базе шифротекстом, а в заказах открытая: сравниваем с
    # расшифрованной. Один адрес на карточку — это один decrypt, не N.
    address = user.email_plain
    if address:
        condition = condition | (Order.email == address)
    return list(
        db.scalars(
            select(Order)
            .where(condition)
            .options(selectinload(Order.plan), selectinload(Order.user))
            .order_by(Order.created_at.desc())
        )
    )


def _detail(db: OrmSession, user_id: int) -> schemas.UserDetail:
    """Карточка целиком: пользователь, связи и его заказы."""
    user = _load(db, user_id)
    return mappers.user_detail(user, orders=_orders(db, user))


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
    ios: bool | None = Query(default=None, description="Только клиенты с ключом для iPhone"),
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
            # Строка уже расшифрована маппером для показа — по ней и ищем:
            # раньше почта находилась через открытую копию в contact, а
            # копии больше нет.
            or needle in (r.email or "").lower()
        ]
    if status_filter and status_filter != "all":
        rows = [r for r in rows if r.status == status_filter]
    if plan and plan != "all":
        rows = [r for r in rows if r.plan == plan]
    if ios is not None:
        rows = [r for r in rows if r.ios_access is ios]
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
            email=body.email,
            traffic_limit_bytes=body.traffic_limit_bytes,
            price=float(body.price) if body.price is not None else None,
        )
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit(db, admin, "user.create", user.public_id, f"логин {user.login}")
    return schemas.UserCreated(
        user=_detail(db, user.id), password=password, warnings=warnings
    )


@router.get("/{user_id}", response_model=schemas.UserDetail)
def get_user(
    user_id: int, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    return _detail(db, user_id)


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
    if body.email is not None:
        address = normalize_email(body.email)
        # Почта — ключ, по которому повторная покупка находит человека.
        # Занятой почтой одного клиента нельзя пометить другого: продление
        # ушло бы не туда. Ищем по слепому индексу — открытых адресов в
        # базе нет.
        if address:
            taken = services.find_by_email(db, address)
            if taken is not None and taken.id != user.id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "эта почта занята другой учёткой")
        user.set_email(address)
    db.commit()
    audit(db, admin, "user.update", user.public_id)
    return _detail(db, user_id)


# --- управление доступом -----------------------------------------------------


@router.post("/{user_id}/enable", response_model=schemas.UserDetail)
def enable_user(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    """Возвращает доступ и заново выдаёт пиры на узлах."""
    user = _load(db, user_id)
    problems = services.set_user_active(db, user, True)
    audit(db, admin, "user.enable", user.public_id)
    detail = _detail(db, user_id)
    if problems:
        detail.blocked_reason = "Не удалось выдать ключи: " + "; ".join(problems)
    return detail


@router.post("/{user_id}/disable", response_model=schemas.UserDetail)
def disable_user(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    """
    Пауза: вход остаётся, но туннель рвётся сразу.

    Пиры снимаются с узлов в тот же момент — иначе уже установленное
    соединение продолжает работать, и «отключён» в панели означает лишь
    «не сможет войти заново».
    """
    user = _load(db, user_id)
    problems = services.set_user_active(db, user, False)
    audit(db, admin, "user.disable", user.public_id)
    detail = _detail(db, user_id)
    if problems:
        # Пира сняли не везде — администратор должен знать, где остался доступ.
        detail.blocked_reason = "Доступ остался на узлах: " + "; ".join(problems)
    return detail


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
    # Через _detail, а не голым маппером: панель подставляет ответ действия
    # прямо в открытую карточку, и без заказов вкладка «Заказы» сразу после
    # блокировки показывала бы «заказов не было» — ровно там, где разбирают
    # «заплатил, а доступа нет».
    detail = _detail(db, user_id)
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
    return _detail(db, user_id)


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
        # Флаг передаём отдельно: без него безлимит записывался как «лимита
        # нет» и тут же откатывался к тарифному, см. set_traffic_limit.
        services.set_traffic_limit(db, user, limit, unlimited=body.unlimited)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "user.traffic_limit", user.public_id, "безлимит" if limit is None else f"{body.limit_gb} ГБ")
    return _detail(db, user_id)


@router.post("/{user_id}/traffic-reset", response_model=schemas.UserDetail)
def reset_traffic(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    user = _load(db, user_id)
    services.reset_traffic(db, user)
    audit(db, admin, "user.traffic_reset", user.public_id)
    return _detail(db, user_id)


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
        # Тариф мог смениться вместе с числом устройств: ключи AmneziaVPN
        # обязаны повторить это, иначе оплачено одно устройство, а
        # подключаются по-прежнему три.
        if user.ios_access:
            services.ios.sync(db, user)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    audit(db, admin, "user.extend", user.public_id, f"{days} дн., {price or 0}")
    return _detail(db, user_id)


# --- ключи AmneziaVPN для iPhone ---------------------------------------------
#
# Приложения под iOS нет, поэтому человек подключается официальным
# AmneziaVPN по ссылке `vpn://`. Управление здесь ровно то же, что и у
# остальных: включить, выключить, перевыпустить. Трафик и срок подписки
# отдельных кнопок не требуют — ключи считаются и гаснут вместе со всем
# остальным доступом учётки.


@router.post("/{user_id}/ios/enable", response_model=schemas.UserDetail)
def enable_ios(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    """
    Включает ключи AmneziaVPN и выдаёт первый.

    Именно первый: остальные заводятся кнопкой «Добавить ключ» — здесь и в
    кабинете. Выдавать сразу пять значит расставить по узлам четыре пира,
    за которыми никто не придёт, и посчитать их в лимитах как настоящие.
    """
    user = _load(db, user_id)
    warnings = services.ios.enable(db, user)
    audit(db, admin, "user.ios_enable", user.public_id, f"ключей {len(user.ios_slots())}")
    detail = _detail(db, user_id)
    if warnings:
        detail.blocked_reason = "Ключи выданы не везде: " + "; ".join(warnings)
    return detail


@router.post("/{user_id}/ios/disable", response_model=schemas.UserDetail)
def disable_ios(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    """
    Отключает ключ: пир уходит с узла, ключ остаётся за учёткой.

    Именно снимает пир, а не «перестаёт выдавать»: ссылка уже лежит у
    человека в Amnezia, и пока пир на узле жив, туннель работает. Включить
    обратно можно тем же ключом — человеку не придётся ничего переставлять.

    Выдать себе ключ заново кнопкой в кабинете он при этом не сможет: иначе
    отключение отменялось бы через полминуты после того, как сделано.
    """
    user = _load(db, user_id)
    problems = services.ios.disable(db, user)
    audit(db, admin, "user.ios_disable", user.public_id)
    detail = _detail(db, user_id)
    if problems:
        detail.blocked_reason = "Доступ остался на узлах: " + "; ".join(problems)
    return detail


@router.delete("/{user_id}/ios", response_model=schemas.UserDetail)
def remove_ios(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    """
    Удаляет ключ совсем — вместе с пиром и строкой в базе.

    После этого человек может выдать себе ключ заново в кабинете, и это
    будет другой ключ: другая пара, другой адрес. Так снимают утёкшую
    ссылку — она становится мусором навсегда, а не ждёт включения.
    """
    user = _load(db, user_id)
    problems = services.ios.remove(db, user)
    audit(db, admin, "user.ios_remove", user.public_id)
    detail = _detail(db, user_id)
    if problems:
        detail.blocked_reason = "Пир снят не везде: " + "; ".join(problems)
    return detail


@router.post("/{user_id}/ios/keys", response_model=schemas.UserDetail)
def add_ios_key(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    """
    Заводит человеку ещё один ключ AmneziaVPN — до потолка на учётку.

    То же действие, что и кнопка в кабинете, и намеренно то же самое: у
    поддержки нет причин выдавать ключ иначе, чем это сделает сам человек,
    а вторая ветка правил здесь означала бы вторую же ветку ошибок.
    """
    user = _load(db, user_id)
    try:
        number, warnings = services.ios.add_key(db, user)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "user.ios_key_add", user.public_id, f"ключ {number}")
    detail = _detail(db, user_id)
    if warnings:
        detail.blocked_reason = "Ключ выдан не везде: " + "; ".join(warnings)
    return detail


@router.delete("/{user_id}/ios/keys/{slot}", response_model=schemas.UserDetail)
def remove_ios_key(
    user_id: int,
    slot: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.UserDetail:
    """Удаляет один ключ насовсем: пир с узлов, строку из базы."""
    user = _load(db, user_id)
    try:
        problems = services.ios.remove_key(db, user, slot)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "user.ios_key_remove", user.public_id, f"ключ {slot}")
    detail = _detail(db, user_id)
    if problems:
        detail.blocked_reason = "Пир снят не везде: " + "; ".join(problems)
    return detail


@router.post("/{user_id}/ios/reissue", response_model=schemas.UserDetail)
def reissue_ios(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.UserDetail:
    """Меняет ключи на новые — когда ссылку переслали дальше."""
    user = _load(db, user_id)
    try:
        problems = services.ios.reissue(db, user)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "user.ios_reissue", user.public_id)
    detail = _detail(db, user_id)
    if problems:
        detail.blocked_reason = "Перевыпуск прошёл не везде: " + "; ".join(problems)
    return detail


@router.post("/{user_id}/password", response_model=schemas.PasswordOut)
def reset_password(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.PasswordOut:
    user = _load(db, user_id)
    password = services.set_password(db, user)
    audit(db, admin, "user.password_reset", user.public_id)
    return schemas.PasswordOut(password=password)


@router.post("/{user_id}/reveal", response_model=schemas.RevealOut)
def reveal_password(
    user_id: int, db: OrmSession = Depends(get_db), admin: Admin = Depends(current_admin)
) -> schemas.RevealOut:
    """
    Показать пароль клиента.

    Единственный способ узнать его после выдачи — и потому единственный
    метод API, у которого запись в журнал не побочный эффект, а смысл.
    Запись делается до расшифровки: если в журнал не удалось написать,
    пароль показывать нельзя.

    POST, а не GET, намеренно: GET попадает в историю браузера, в логи
    прокси и в предзагрузку ссылок, а этот запрос не должен случаться сам
    собой.
    """
    user = _load(db, user_id)
    audit(db, admin, "user.password_reveal", user.public_id, f"логин {user.login}")
    try:
        return schemas.RevealOut(password=services.reveal_password(user))
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.delete("/{user_id}/sessions/{session_id}", response_model=schemas.ActionResult)
def kill_session(
    user_id: int,
    session_id: int,
    db: OrmSession = Depends(get_db),
    admin: Admin = Depends(current_admin),
) -> schemas.ActionResult:
    """
    Отключить устройство человека.

    Токен гасится и пир этого устройства снимается с узлов: до появления
    пиров на устройство отсюда уходил один `revoked_at`, приложение
    показывало «войдите заново», а туннель продолжал работать до
    перезагрузки. Тот же код, что и в кабинете, — иначе две кнопки с одной
    подписью однажды начали бы делать разное.
    """
    user = _load(db, user_id)
    problems = services.disconnect_device_by_id(db, user, session_id)
    if problems is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    audit(db, admin, "session.kill", str(session_id))
    return schemas.ActionResult(
        ok=True,
        warnings=problems,
        message="устройство отключено" if not problems else "токен погашен, но узлы ответили не все",
    )


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
