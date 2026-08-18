"""
API публичного сайта: тарифы, заказы, вебхуки провайдеров, личный кабинет.

Живёт в том же префиксе `/api/v1`, что и API приложений, — читатель у них
один и тот же человек, просто с разных экранов. Вход в личный кабинет —
тот же `/api/v1/login`, что и в приложении: заводить второй способ входа
значит завести второе место, где ошибаются с проверкой пароля.

Ключей и конфигов для приложений здесь нет: их выдаёт `/api/v1/servers` по
токену приложения, и в кабинете им делать нечего.

Единственное исключение — ключи `vpn://` для iPhone. Приложения под iOS
нет, человек подключается официальным AmneziaVPN, и получить ключ ему
физически неоткуда, кроме кабинета. Правило при этом остаётся прежним:
ключ отдаётся только по токену входа, только своему владельцу и только
тому, у кого этот доступ включён. См. services/ios.py.
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import payments, services
from .config import settings
from .db import get_db
from .models import (
    HANDSHAKE_WINDOW,
    IOS_MAX_KEYS,
    AppRelease,
    AuditLog,
    DeliveryJob,
    Order,
    OrderStatus,
    Plan,
    Session,
    User,
    normalize_email,
    utcnow,
)
from .payments.base import WebhookRejected
from .security import client_ip, verify_password

log = logging.getLogger("panel.public")

router = APIRouter(prefix="/api/v1", tags=["site"])

# Проверка адреса своими силами вместо pydantic.EmailStr. Тот тянет
# email-validator ради полной сверки с RFC, а нам нужно отсечь опечатки и
# заведомый мусор: настоящую проверку всё равно делает письмо, которое
# либо дойдёт, либо нет.
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$"


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
    # Можно ли оформить заказ. У пробного периода — нет: его выдаёт
    # регистрация, а платёжная форма на ноль рублей не открывается.
    purchasable: bool = True


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
        purchasable=plan.price_kopecks > 0,
    )


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: OrmSession = Depends(get_db)) -> list[PlanOut]:
    """
    Витрина тарифов. Сайт берёт отсюда цены, сроки, трафик и устройства, а
    не из своей вёрстки: иначе правка в панели до страницы не доезжает.

    Пробный период тоже здесь — с `purchasable: false`. Витрина показывает
    его отдельной полосой, а не карточкой с кнопкой оплаты.
    """
    return [_plan_out(plan) for plan in services.site_plans(db)]


# --- заказы -------------------------------------------------------------------


class OrderIn(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)
    telegram_id: int | None = None
    # С какого устройства покупают. Сайт может сказать прямо; если молчит,
    # платформу определяет сервер по строке браузера. Значение решает ровно
    # один вопрос — готовить ли ключ для AmneziaVPN, см. fulfil.
    platform: str | None = Field(default=None, max_length=16)


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

    Пароль появляется здесь, только пока заказ свежеоплачен и учётка только
    что создана, — см. ORDER_PASSWORD_WINDOW. При продлении пароля нет: он
    не менялся, и показывать человеку старый пароль незачем.
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
            # Что сказал сайт, а иначе — что видно по браузеру. Определять
            # платформу надо сейчас: к приходу вебхука заголовков уже нет,
            # а решение «нужен ли ключ для AmneziaVPN» принимается там.
            platform=body.platform
            or services.orders.platform_from_user_agent(request.headers.get("user-agent")),
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


# Сколько после оплаты этот метод ещё отдаёт пароль. Окно по времени, а не
# «ровно один показ»: страница успеха опрашивает метод в цикле, тот же вызов
# делает страница оплаты при загрузке, и единственный показ сжигали бы
# перезагрузка вкладки, кнопка «назад» или оборванная мобильная сеть —
# человек остался бы без пароля, который больше нигде не показывается.
#
# Пятнадцати минут хватает, чтобы дождаться вебхука и переписать пароль, и
# мало, чтобы идентификатор заказа из истории браузера, чужого экрана или
# переписки с поддержкой оставался ключом к чужому VPN.
ORDER_PASSWORD_WINDOW = dt.timedelta(minutes=15)

PASSWORD_SHOWN_ACTION = "order.password_shown"


def _password_window_open(order: Order) -> bool:
    if order.paid_at is None:
        return False
    return utcnow() - order.paid_at <= ORDER_PASSWORD_WINDOW


@router.get("/orders/{order_id}/status", response_model=OrderStatusOut)
def order_status(
    order_id: str, response: Response, db: OrmSession = Depends(get_db)
) -> OrderStatusOut:
    """
    Статус заказа для страницы успеха.

    Возврат человека на `/success` ничего не подтверждает: этот адрес можно
    набрать руками. Подтверждает только вебхук, и страница ждёт именно его,
    опрашивая этот метод.

    Пароль отдаётся по идентификатору заказа, без входа: идентификатор —
    случайный uuid, известный только тому, кто оформил заказ. Но он же лежит
    в адресной строке, а значит в истории браузера и в логах, и его просят
    назвать поддержке — поэтому доступ к паролю живёт ORDER_PASSWORD_WINDOW
    от момента оплаты, а не вечно, и первый показ попадает в журнал.
    Кэшировать такой ответ нельзя ни браузеру, ни прокси.
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

    if not order.is_renewal and _password_window_open(order):
        # Пароль показываем только для новой учётки и только внутри окна
        # после оплаты. Расшифровка — из того же шифра, что и в админке, и
        # запись в журнал делается до неё, как в admin_api/users.py: если
        # расшифровка упадёт, факт обращения всё равно останется.
        #
        # Строку пишем одну на заказ, а не на каждый опрос: страница
        # опрашивает этот метод десятки раз за полторы минуты.
        shown = db.scalar(
            select(AuditLog.id).where(
                AuditLog.action == PASSWORD_SHOWN_ACTION, AuditLog.target == order.id
            )
        )
        if shown is None:
            db.add(
                AuditLog(
                    admin_id=None,
                    action=PASSWORD_SHOWN_ACTION,
                    target=order.id,
                    detail=f"логин {user.login}",
                )
            )
            db.commit()
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
    # Идёт ли через это устройство трафик прямо сейчас. По рукопожатию пира,
    # а не по тому, открыто ли приложение: это разные события.
    is_connected: bool = False


class PaymentOut(BaseModel):
    amount: float
    currency: str = "RUB"
    comment: str | None = None
    paid_at: dt.datetime


class IosKeyOut(BaseModel):
    """
    Ключ AmneziaVPN для одного устройства.

    Ключ на устройство, а не на учётку, и это не прихоть формата: один пир
    нельзя честно поделить между телефонами — сервер помнит у пира один
    адрес подключения, и второе устройство отбирает соединение у первого.
    Поэтому «три телефона» — это три разные ссылки.
    """

    slot: int
    name: str
    server_id: int
    server: str
    country: str | None = None
    country_code: str | None = None
    city: str | None = None
    vpn_url: str
    traffic_bytes: int = 0
    last_handshake_at: dt.datetime | None = None
    # Когда ключ выдан. Нужно человеку: после перевыпуска в кабинете лежит
    # другая ссылка, и по дате видно, что это уже не та, что вставлена в
    # Amnezia, — иначе перемена молчаливая.
    created_at: dt.datetime | None = None
    is_connected: bool = False


class IosOut(BaseModel):
    available: bool = False
    # Отключён администратором: ключа нет и выдать себе новый нельзя.
    blocked: bool = False
    keys: list[IosKeyOut] = []
    # Сколько ключей человек может завести всего и сколько уже завёл.
    # Кабинету нужны оба числа: он пишет «2 из 5» и гасит кнопку на потолке,
    # а считать ключи по списку он не может — там строка на каждую страну.
    max_keys: int = IOS_MAX_KEYS
    keys_count: int = 0
    # Можно ли завести ещё один прямо сейчас. Ответ считает сервер: кроме
    # потолка сюда входят подписка и отключение администратором, и
    # повторять эти правила в кабинете значит однажды разойтись с ними.
    can_add: bool = False
    guide_url: str | None = None
    # Почему ключей нет, хотя доступ включён: узлы ещё готовят пиры или
    # подписка кончилась. Пустой список без объяснения — тупик.
    notice: str | None = None


class TunnelFileOut(BaseModel):
    """
    Что показать о файле обхода до скачивания.

    Едет и отдельным запросом (его делает бот), и внутри ответа кабинета.
    Второе важнее: кабинет и так спрашивает `/account`, а лишний запрос —
    это лишний повод чему-то не доехать и убрать кнопку с глаз.
    """

    available: bool = False
    filename: str | None = None
    version: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    note: str | None = None
    updated_at: dt.datetime | None = None
    url: str = "/api/v1/tunnel-file/download"


class AccountOut(BaseModel):
    login: str
    email: str | None = None
    public_id: str
    plan: str | None = None
    plan_title: str | None = None
    period_days: int | None = None
    price: float | None = None
    active: bool
    expires_at: dt.datetime | None = None
    days_left: int | None = None
    device_limit: int
    devices: list[DeviceOut]
    traffic_used_bytes: int = 0
    traffic_limit_bytes: int | None = None
    payments: list[PaymentOut] = []
    ios: IosOut = IosOut()
    tunnel_file: TunnelFileOut = TunnelFileOut()


def _device_connected(user: User, device_id: str, now: dt.datetime) -> bool:
    """
    Есть ли свежее рукопожатие у пиров этого устройства.

    Спрашиваем узел, а не приложение: приложение может быть закрыто при
    поднятом туннеле и открыто при опущенном.
    """
    for key in user.keys:
        if key.revoked_at is not None or (key.device_id or "") != device_id:
            continue
        if key.last_handshake_at is not None and key.last_handshake_at > now - HANDSHAKE_WINDOW:
            return True
    return False


def _ios_out(user: User, now: dt.datetime) -> IosOut:
    """
    Ключи для AmneziaVPN — только тем, кому этот доступ включён.

    Пометка на учётке ставится покупкой с iPhone или кнопкой в кабинете, и
    без неё блока в ответе нет вовсе: остальным людям он не нужен и только
    сбивал бы с толку.
    """
    if not user.ios_access:
        return IosOut(available=False, guide_url=settings().guide_link)

    if user.ios_blocked:
        # Отключён администратором. Кнопки выдачи нет: иначе решение
        # отменялось бы нажатием через полминуты после того, как принято.
        return IosOut(
            available=True,
            blocked=True,
            guide_url=settings().guide_link,
            notice="Ключи отключены. Напишите в поддержку — разберёмся, в чём дело.",
        )

    keys = [
        IosKeyOut(
            slot=key.slot,
            name=key.name,
            server_id=key.server_id,
            server=key.country or key.server_name,
            country=key.country,
            country_code=key.country_code,
            city=key.city,
            vpn_url=key.vpn_url,
            traffic_bytes=key.traffic_bytes,
            last_handshake_at=key.last_handshake_at,
            created_at=key.created_at,
            is_connected=(
                key.last_handshake_at is not None
                and key.last_handshake_at > now - HANDSHAKE_WINDOW
            ),
        )
        for key in services.ios.keys(user)
    ]

    notice = None
    if not keys:
        if not user.has_access(now):
            notice = "Ключи отключены: подписка кончилась или закрыт доступ."
        else:
            notice = "Готовим ключи, это займёт около минуты — обновите страницу."

    # Ключей у человека столько, сколько номеров, а не строк: на каждый
    # номер приходится по ссылке на каждую страну.
    used = len({key.slot for key in keys})
    return IosOut(
        available=True,
        keys=keys,
        max_keys=IOS_MAX_KEYS,
        keys_count=used,
        can_add=user.has_access(now) and services.ios.free_slot(user) is not None,
        guide_url=settings().guide_link,
        notice=notice,
    )


def _tunnel_out(db: OrmSession) -> TunnelFileOut:
    entry = services.tunnel.current(db)
    if entry is None:
        return TunnelFileOut(available=False)
    return TunnelFileOut(
        available=True,
        filename=entry.filename,
        version=entry.version,
        size_bytes=entry.size_bytes,
        sha256=entry.sha256,
        note=entry.note,
        updated_at=entry.updated_at,
    )


def _account_out(db: OrmSession, user: User, current: Session) -> AccountOut:
    subscription = user.active_subscription()
    plan = subscription.plan_ref if subscription else None
    now = utcnow()

    return AccountOut(
        login=user.login,
        # Свой адрес человек видеть может — шифрование защищает базу от
        # утечки, а не почту от её владельца.
        email=user.email_plain,
        public_id=user.public_id,
        plan=subscription.plan if subscription else None,
        plan_title=plan.name if plan else None,
        period_days=plan.period_days if plan else None,
        price=float(subscription.price) if subscription and subscription.price else None,
        active=user.has_access(now),
        expires_at=subscription.expires_at if subscription else None,
        days_left=max(0, (subscription.expires_at - now).days) if subscription else None,
        device_limit=user.device_limit(now),
        # Только приложения. Вкладка браузера, из которой человек читает эту
        # самую страницу, устройством не является: туннеля в ней нет,
        # отключать нечего, а место в лимите тарифа она занимала.
        devices=[
            DeviceOut(
                id=session.id,
                name=session.device_name,
                platform=session.platform,
                app_version=session.app_version,
                last_seen_at=session.last_seen_at,
                created_at=session.created_at,
                is_current=session.id == current.id,
                is_connected=_device_connected(user, session.device_key, now),
            )
            for session in sorted(
                user.device_sessions(now), key=lambda s: s.last_seen_at, reverse=True
            )
        ],
        traffic_used_bytes=user.traffic_used_bytes,
        traffic_limit_bytes=user.effective_traffic_limit(now),
        payments=[
            PaymentOut(
                amount=float(payment.amount),
                currency=payment.currency,
                comment=payment.comment,
                paid_at=payment.paid_at,
            )
            for payment in sorted(user.payments, key=lambda p: p.paid_at, reverse=True)
        ],
        ios=_ios_out(user, now),
        tunnel_file=_tunnel_out(db),
    )


@router.get("/account", response_model=AccountOut)
def account(
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    user, session = who
    # В ответе могут быть ссылки `vpn://` — это рабочий доступ к VPN, и
    # оседать в кэше браузера или прокси ему нечего.
    response.headers["Cache-Control"] = "no-store"
    return _account_out(db, user, session)


@router.post("/account/ios", response_model=AccountOut)
def enable_ios(
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    """
    «У меня iPhone» — выдать ключи для AmneziaVPN.

    Покупка с iPhone включает это сама, но случаев мимо неё хватает:
    оплатили с ноутбука, подарили доступ, купили до появления ключей.
    Просить за этим поддержку незачем — ничего нового человек так не
    получает: ключи считают тот же трафик и гаснут по тому же концу
    подписки, что и приложение.
    """
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    if user.ios_blocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "ключ отключён — напишите в поддержку",
            headers={"X-Error-Code": "ios_blocked"},
        )

    if not user.has_access():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ключ выдаётся по действующей подписке — оплатите тариф",
            headers={"X-Error-Code": "no_subscription"},
        )

    # Повторное нажатие ничего не удваивает: ключ на учётку один, и если он
    # уже есть — просто отдаём кабинет с ним. А вот когда пометка стоит, а
    # живого ключа нет (узел не ответил в прошлый раз), выдачу повторяем:
    # иначе человек остаётся с кнопкой, которая «уже нажата», и без ключа.
    if not user.ios_access:
        warnings = services.ios.enable(db, user)
    elif not services.ios.keys(user):
        warnings = services.ios.sync(db, user)
    else:
        warnings = []

    for warning in warnings:
        log.warning("ключ AmneziaVPN для %s: %s", user.public_id, warning)
    return _account_out(db, user, session)


@router.post("/account/ios/keys", response_model=AccountOut)
def add_ios_key(
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    """
    «Добавить ключ» — ещё один `vpn://` на то же имя, до `IOS_MAX_KEYS`.

    Второй телефон это второй ключ, а не тот же самый: пир помнит один
    адрес подключения, и два устройства на одной ссылке отбирают туннель
    друг у друга — по очереди, молча и без единой ошибки на экране.

    Пир заводится внутри запроса, а не фоном. Человек нажал кнопку и ждёт
    ссылку: ответ с пустым списком и обещанием «скоро появится» здесь
    ничем не лучше ошибки.
    """
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    try:
        number, warnings = services.ios.add_key(db, user)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_add_failed"}
        ) from exc

    for warning in warnings:
        log.warning("ключ %s AmneziaVPN для %s: %s", number, user.public_id, warning)
    return _account_out(db, user, session)


@router.delete("/account/ios/keys/{slot}", response_model=AccountOut)
def delete_ios_key(
    slot: int,
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    """
    Удаляет один ключ — тот, что перестал быть нужен или куда-то уехал.

    Удаляет насовсем: пир снимается с узлов, строка сносится, и та же
    ссылка больше не вернётся. Иначе кнопка не решала бы задачу, ради
    которой она есть, — ссылку у ключа не сменить паролем, и утёкшая
    ссылка это и есть утёкший доступ.
    """
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    try:
        problems = services.ios.remove_key(db, user, slot)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_remove_failed"}
        ) from exc

    for problem in problems:
        log.warning("ключ %s AmneziaVPN для %s: %s", slot, user.public_id, problem)
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


class EmailIn(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)


@router.post("/account/email")
def set_account_email(
    body: EmailIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    """
    Привязка почты из кабинета: на неё уходят чеки и доступ при продлении.

    Учётка, купленная на сайте, рождается с почтой, а заведённая
    регистрацией или администратором — может жить без неё. Без адреса
    продление из кабинета упирается в «нет почты», и человеку некуда было
    нажать. Хранится адрес так же, как у всех: шифротекстом со слепым
    индексом, открытого поля в базе нет.
    """
    user, _ = who
    address = normalize_email(body.email)

    # Занятой почтой одного клиента нельзя пометить другого: продление по
    # этому адресу ушло бы не туда.
    taken = services.find_by_email(db, address)
    if taken is not None and taken.id != user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "эта почта уже привязана к другой учётке",
            headers={"X-Error-Code": "email_taken"},
        )

    previous = user.email_plain
    user.set_email(address)

    # Письмо на новый адрес — не вежливость, а проверка.
    #
    # Человек мог ошибиться в букве, и тогда чеки и напоминания годами уходят
    # в никуда, а он считает, что мы их не шлём. Пришедшее письмо доказывает,
    # что адрес рабочий и принадлежит ему. Ставим в очередь, а не отправляем
    # тут же: почтовый провайдер может не ответить, и это не повод отказать в
    # сохранении адреса.
    if address and address != previous:
        db.add(
            DeliveryJob(
                channel="email",
                template="email_attached",
                target=address,
                user_id=user.id,
            )
        )

    db.commit()
    return {"ok": True, "email": address}


@router.delete("/account/devices/{device_id}")
def unlink_device(
    device_id: int,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    """
    Отключить устройство из кабинета.

    Не «забыть о нём», а отключить: токен гаснет и пир уходит с узлов, то
    есть туннель на том устройстве падает сразу. Раньше здесь стоял один
    `revoked_at`, строка пропадала из списка, а человек на том ноутбуке
    продолжал сидеть в VPN — кнопка обещала больше, чем делала.
    """
    user, _ = who
    problems = services.disconnect_device_by_id(db, user, device_id)
    if problems is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "устройство не найдено")
    # Узел не ответил — доступ там мог остаться, и молчать об этом нельзя.
    # Сессия при этом уже погашена, поэтому это предупреждение, а не отказ.
    return {"ok": True, "problems": problems}


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
    email = user.email_plain
    if not email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "к учётке не привязана почта — добавьте её в кабинете",
            headers={"X-Error-Code": "email_required"},
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
            email=email,
            telegram_id=user.telegram_id,
            ip=client_ip(request),
            # Продление с iPhone — тот же повод выдать ключ AmneziaVPN, что
            # и первая покупка: приложения там по-прежнему нет.
            platform=(
                "ios"
                if user.ios_access
                else services.orders.platform_from_user_agent(request.headers.get("user-agent"))
            ),
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


# --- файл раздельного туннелирования -----------------------------------------


@router.get("/tunnel-file", response_model=TunnelFileOut)
def tunnel_file(db: OrmSession = Depends(get_db)) -> TunnelFileOut:
    """
    Сведения о файле обхода: есть ли он, когда обновлялся, сколько весит.

    Без токена: это список сайтов, а не доступ. Его спрашивает бот; кабинету
    отдельный запрос не нужен — те же поля лежат в ответе `/account`.
    """
    return _tunnel_out(db)


@router.get("/tunnel-file/download", include_in_schema=False)
def tunnel_file_download(db: OrmSession = Depends(get_db)) -> Response:
    entry = services.tunnel.current(db)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "файл ещё не загружен")

    media = "application/json" if entry.filename.lower().endswith(".json") else "text/plain"
    return Response(
        content=entry.content,
        media_type=f"{media}; charset=utf-8",
        headers={
            # filename* по RFC 5987 — имя может быть и кириллическим.
            "Content-Disposition": f'attachment; filename="{entry.filename}"',
            # Файл меняется часто, и отдать вчерашний список хуже, чем
            # сходить за ним ещё раз: сайты из него человек не увидит.
            "Cache-Control": "no-cache",
        },
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
