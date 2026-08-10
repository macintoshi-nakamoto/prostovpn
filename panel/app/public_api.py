"""
API публичного сайта: тарифы, заказы, вебхуки провайдеров, личный кабинет.

Живёт в том же префиксе `/api/v1`, что и API приложений, — читатель у них
один и тот же человек, просто с разных экранов. Вход в личный кабинет —
тот же `/api/v1/login`, что и в приложении: заводить второй способ входа
значит завести второе место, где ошибаются с проверкой пароля.

Ключей, конфигов и `vpn://` ни в одном ответе этого модуля нет и быть не
может. Личный кабинет показывает срок подписки, устройства и кнопку
продления — всё, что человеку положено видеть.
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from . import payments, services
from .config import settings
from .db import get_db
from .models import AppRelease, OrderStatus, Plan, Session, User, utcnow
from .payments.base import WebhookRejected
from .security import verify_password

log = logging.getLogger("panel.public")

router = APIRouter(prefix="/api/v1", tags=["site"])

# Проверка адреса своими силами вместо pydantic.EmailStr. Тот тянет
# email-validator ради полной сверки с RFC, а нам нужно отсечь опечатки и
# заведомый мусор: настоящую проверку всё равно делает письмо, которое
# либо дойдёт, либо нет.
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$"


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# --- тарифы -------------------------------------------------------------------


class PlanOut(BaseModel):
    """
    Тариф глазами сайта.

    Цена уходит копейками и рублями сразу: считать по копейкам, показывать
    по рублям. Форматировать цену на сервере нельзя — вёрстка ставит разряды
    и знак валюты по-своему; а считать её на клиенте из рублей значит
    однажды получить 299.99999.
    """

    code: str
    title: str
    tagline: str | None = None
    price_kopecks: int
    currency: str
    duration_days: int
    server_limit: int
    device_limit: int
    allowed_regions: list[str] | None = None
    traffic_limit_bytes: int | None = None


def _plan_out(plan: Plan) -> PlanOut:
    return PlanOut(
        code=plan.code,
        title=plan.name,
        tagline=plan.tagline,
        price_kopecks=plan.price_kopecks,
        currency=plan.currency,
        duration_days=plan.period_days,
        server_limit=plan.server_limit,
        device_limit=plan.device_limit,
        allowed_regions=plan.allowed_regions,
        traffic_limit_bytes=plan.traffic_limit_bytes,
    )


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: OrmSession = Depends(get_db)) -> list[PlanOut]:
    """Витрина тарифов. Сайт берёт цены отсюда, а не из своей вёрстки."""
    return [_plan_out(plan) for plan in services.public_plans(db)]


# --- заказы -------------------------------------------------------------------


class OrderIn(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)
    telegram_id: int | None = None


class OrderOut(BaseModel):
    id: str
    status: str
    plan_code: str
    amount_kopecks: int
    currency: str
    redirect_url: str | None = None
    created_at: dt.datetime


class OrderStatusOut(BaseModel):
    """
    То, что опрашивает страница успеха.

    Логин и пароль появляются здесь ровно один раз — когда заказ стал
    оплаченным и учётка только что создана. При продлении пароля нет: он не
    менялся, и показывать человеку старый пароль незачем.
    """

    id: str
    status: str
    plan_code: str
    amount_kopecks: int
    currency: str = "RUB"
    is_renewal: bool = False
    login: str | None = None
    password: str | None = None
    expires_at: dt.datetime | None = None
    email: str | None = None


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: OrderIn, request: Request, db: OrmSession = Depends(get_db)
) -> OrderOut:
    """
    Заводит заказ и возвращает ссылку на оплату.

    Ограничение по адресу — не от жадности: без него формой заказа набивают
    базу тысячей `pending`-строк за минуту, а вместе с ними тысячей
    зарегистрированных платежей на стороне провайдера.
    """
    ip = client_ip(request)
    verdict = services.ratelimit.hit(
        db, f"order:{ip or 'unknown'}", limit=settings().order_max_per_hour, window_minutes=60
    )
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "слишком много заказов с этого адреса, попробуйте позже",
            headers={"Retry-After": str(verdict.retry_after)},
        )

    try:
        order = services.create_order(
            db,
            plan_code=body.plan_code,
            email=str(body.email),
            telegram_id=body.telegram_id,
            ip=ip,
        )
    except services.OrderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return OrderOut(
        id=order.id,
        status=order.status,
        plan_code=order.plan_code,
        amount_kopecks=order.amount_kopecks,
        currency=order.currency,
        redirect_url=order.redirect_url,
        created_at=order.created_at,
    )


@router.get("/orders/{order_id}/status", response_model=OrderStatusOut)
def order_status(
    order_id: str, response: Response, db: OrmSession = Depends(get_db)
) -> OrderStatusOut:
    """
    Статус заказа для страницы успеха.

    Возврат человека на `/success` ничего не подтверждает: этот адрес можно
    набрать руками. Подтверждает только вебхук, и страница ждёт именно его,
    опрашивая этот метод.

    Пароль отдаётся по идентификатору заказа, и это осознанное решение:
    идентификатор — случайный uuid, известный только тому, кто оформил
    заказ, и живёт он до первого показа. Кэшировать такой ответ нельзя ни
    браузеру, ни прокси.
    """
    response.headers["Cache-Control"] = "no-store"

    order = services.orders.find(db, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "заказ не найден")

    out = OrderStatusOut(
        id=order.id,
        status=order.status,
        plan_code=order.plan_code,
        amount_kopecks=order.amount_kopecks,
        currency=order.currency,
        is_renewal=order.is_renewal,
        # Почта из самого заказа, и до оплаты тоже: человек сам её только что
        # ввёл, а увидев её на странице оплаты, успеет заметить опечатку до
        # того, как письмо уйдёт в никуда.
        email=order.email,
    )
    if order.status != OrderStatus.PAID.value or not order.user_id:
        return out

    user = db.get(User, order.user_id)
    if user is None:
        return out

    subscription = user.active_subscription()
    out.login = user.login
    out.expires_at = subscription.expires_at if subscription else None

    if not order.is_renewal:
        # Пароль показываем только для новой учётки и только пока человек не
        # ушёл со страницы. Расшифровка — из того же шифра, что и в админке.
        try:
            out.password = services.reveal_password(user)
        except services.PanelError as exc:
            log.warning("пароль для страницы успеха недоступен: %s", exc)
    return out


# --- вебхуки провайдеров ------------------------------------------------------


@router.post("/billing/webhook/{provider_name}", include_in_schema=False)
async def billing_webhook(
    provider_name: str, request: Request, db: OrmSession = Depends(get_db)
) -> Response:
    """
    Единственный триггер выдачи доступа.

    Ответ почти всегда 200: как только событие записано, провайдеру больше
    незачем его повторять. 500 здесь заставил бы его долбить эндпоинт и
    повышал бы шанс параллельной обработки на соседних воркерах.

    Ни CORS, ни кук: этот адрес зовёт сервер провайдера, а не браузер.
    """
    raw_body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    ip = client_ip(request)

    try:
        payments.get(provider_name)
    except payments.UnknownProvider:
        log.warning("вебхук неизвестного провайдера %r с адреса %s", provider_name, ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "неизвестный провайдер") from None

    try:
        result = services.billing_webhook.handle(
            db, provider_name=provider_name, headers=headers, raw_body=raw_body, client_ip=ip
        )
    except WebhookRejected as exc:
        # Неподписанное уведомление — 403 и запись в лог. Тело не разбираем
        # и в базу не кладём: это данные неизвестного происхождения.
        log.error("вебхук %s отклонён с адреса %s: %s", provider_name, ip, exc)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "подпись не подтверждена") from exc

    return Response(
        content=f'{{"result":"{result.result}"}}',
        media_type="application/json",
        status_code=result.http_status,
    )


class MockPayIn(BaseModel):
    order_id: str


@router.post("/billing/mock/pay", include_in_schema=False)
def mock_pay(body: MockPayIn, db: OrmSession = Depends(get_db)) -> dict[str, object]:
    """
    Кнопка «Оплатить» на демонстрационной форме.

    Существует только в режиме имитации. На боевом провайдере этот адрес
    отвечает 404: иначе он был бы кнопкой «выдать себе подписку бесплатно».
    """
    if payments.active_name() != payments.MockProvider.name:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "не найдено")

    order = services.orders.find(db, body.order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "заказ не найден")
    if order.status != OrderStatus.PENDING.value:
        return {"ok": True, "status": order.status}

    from .payments.mock import dispatch

    dispatch(order.id, "succeeded")
    return {"ok": True, "status": order.status}


# --- личный кабинет -----------------------------------------------------------


def current_user(
    request: Request, db: OrmSession = Depends(get_db)
) -> tuple[User, Session]:
    """Тот же токен, что у приложения: кабинет — просто ещё один экран."""
    authorization = request.headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен токен")
    session = services.session_for_token(db, authorization.split(" ", 1)[1].strip())
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен недействителен")
    return session.user, session


class DeviceOut(BaseModel):
    id: int
    name: str | None = None
    platform: str | None = None
    app_version: str | None = None
    last_seen_at: dt.datetime
    created_at: dt.datetime
    is_current: bool = False


class AccountOut(BaseModel):
    login: str
    email: str | None = None
    public_id: str
    plan: str | None = None
    plan_title: str | None = None
    active: bool
    expires_at: dt.datetime | None = None
    days_left: int | None = None
    device_limit: int
    devices: list[DeviceOut]
    traffic_used_bytes: int = 0
    traffic_limit_bytes: int | None = None


def _account_out(db: OrmSession, user: User, current: Session) -> AccountOut:
    subscription = user.active_subscription()
    plan = subscription.plan_ref if subscription else None
    now = utcnow()

    return AccountOut(
        login=user.login,
        email=user.email,
        public_id=user.public_id,
        plan=subscription.plan if subscription else None,
        plan_title=plan.name if plan else None,
        active=user.has_access(now),
        expires_at=subscription.expires_at if subscription else None,
        days_left=max(0, (subscription.expires_at - now).days) if subscription else None,
        device_limit=user.device_limit(now),
        devices=[
            DeviceOut(
                id=session.id,
                name=session.device_name,
                platform=session.platform,
                app_version=session.app_version,
                last_seen_at=session.last_seen_at,
                created_at=session.created_at,
                is_current=session.id == current.id,
            )
            for session in sorted(user.live_sessions(now), key=lambda s: s.last_seen_at, reverse=True)
        ],
        traffic_used_bytes=user.traffic_used_bytes,
        traffic_limit_bytes=user.effective_traffic_limit(now),
    )


@router.get("/account", response_model=AccountOut)
def account(
    who: tuple[User, Session] = Depends(current_user), db: OrmSession = Depends(get_db)
) -> AccountOut:
    user, session = who
    return _account_out(db, user, session)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/account/password")
def change_password(
    body: PasswordChangeIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    """
    Смена пароля из кабинета.

    Старый пароль спрашиваем обязательно: токен мог утечь, и без этой
    проверки утёкший токен превращался бы в захват учётки навсегда.
    """
    user, session = who
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "текущий пароль неверен")

    services.set_password(db, user, body.new_password)
    # set_password гасит все сессии, включая текущую: человек вводит новый
    # пароль заново на каждом устройстве, и это правильно.
    return {"ok": True, "relogin_required": True}


@router.delete("/account/devices/{device_id}")
def unlink_device(
    device_id: int,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> dict[str, bool]:
    user, _ = who
    target = db.get(Session, device_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "устройство не найдено")
    target.revoked_at = utcnow()
    db.commit()
    return {"ok": True}


class RenewIn(BaseModel):
    plan_code: str | None = None


@router.post("/account/renew", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def renew(
    body: RenewIn,
    request: Request,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> OrderOut:
    """
    Продление из кабинета — обычный заказ на ту же почту.

    Отдельного пути для продления нет намеренно: он прошёл бы мимо вебхука,
    мимо сверки суммы и мимо идемпотентности, то есть мимо всего, ради чего
    оплата и устроена так, как устроена.
    """
    user, _ = who
    if not user.email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "к учётке не привязана почта — напишите в поддержку",
        )

    plan_code = body.plan_code
    if not plan_code:
        subscription = user.active_subscription()
        plan_code = subscription.plan if subscription else None
    if not plan_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "выберите тариф")

    try:
        order = services.create_order(
            db,
            plan_code=plan_code,
            email=user.email,
            telegram_id=user.telegram_id,
            ip=client_ip(request),
        )
    except services.OrderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return OrderOut(
        id=order.id,
        status=order.status,
        plan_code=order.plan_code,
        amount_kopecks=order.amount_kopecks,
        currency=order.currency,
        redirect_url=order.redirect_url,
        created_at=order.created_at,
    )


# --- скачивание ---------------------------------------------------------------


class DownloadOut(BaseModel):
    platform: str
    version: str
    url: str
    size_bytes: int | None = None
    released_at: dt.datetime


@router.get("/downloads", response_model=list[DownloadOut])
def downloads(db: OrmSession = Depends(get_db)) -> list[DownloadOut]:
    """Ссылки на установщики для страницы скачивания."""
    out: list[DownloadOut] = []
    for platform in ("windows", "android", "ios", "macos", "linux"):
        release: AppRelease | None = services.latest_for(db, platform)
        if release is None:
            continue
        out.append(
            DownloadOut(
                platform=platform,
                version=release.version,
                url=release.url,
                size_bytes=release.size_bytes,
                released_at=release.released_at,
            )
        )
    return out
