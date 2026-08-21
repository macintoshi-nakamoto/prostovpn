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
    ios_slot_number,
    normalize_email,
    utcnow,
)
from .payments import platega
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

    out.login = user.login
    # Общий конец доступа: при продлении важен он, а не срок текущего периода.
    out.expires_at = user.access_expires_at()

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
        if provider_name == payments.PlategaProvider.name:
            # Подлинность до разбора: у Platega один адрес на все события, и
            # прежде чем смотреть, платёж это или подписка, сверяем секрет.
            platega.authenticate(headers)
            if platega.is_subscription_event(raw_body):
                result = services.recurring.handle_webhook(
                    db, headers=headers, raw_body=raw_body, client_ip=ip
                )
            else:
                result = services.billing_webhook.handle(
                    db, provider_name=provider_name, headers=headers, raw_body=raw_body, client_ip=ip
                )
        else:
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
    # Что за строка: вход приложения (`app`) или ключ AmneziaVPN
    # (`ios_key`). За ключом нет ни токена, ни входа — это пир, который
    # человек вставил ссылкой в Amnezia, — поэтому и отключается он своим
    # маршрутом, а не DELETE /account/devices/{id}.
    kind: str = "app"
    # Номер ключа AmneziaVPN — только у строк kind="ios_key". У них же id
    # отрицательный (минус номер), чтобы не пересечься с номерами сессий у
    # читателей, различающих строки только по id.
    slot: int | None = None
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
    # Отключён самим человеком из списка устройств. Ссылка за слотом
    # осталась и вернётся кнопкой «включить» — той же самой.
    disconnected: bool = False


class IosOut(BaseModel):
    available: bool = False
    # Отключён администратором: ключа нет и выдать себе новый нельзя.
    blocked: bool = False
    keys: list[IosKeyOut] = []
    # Ключи, отключённые самим человеком. Отдельным списком, а не флагом в
    # общем: `keys` читают и бот, и старые сборки кабинета как «рабочие
    # ссылки», и мёртвая ссылка среди них выглядела бы живой.
    disconnected_keys: list[IosKeyOut] = []
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


class UpcomingOut(BaseModel):
    """
    Оплаченный период, который ещё не начался.

    Появляется при смене тарифа: новый встаёт в очередь за текущим, и
    кабинет обязан показать, что деньги не пропали — сначала дожидаются
    оставшиеся дни, потом в полную силу вступает новый тариф.
    """

    plan: str
    plan_title: str | None = None
    starts_at: dt.datetime
    expires_at: dt.datetime
    period_days: int


class AccountOut(BaseModel):
    login: str
    email: str | None = None
    public_id: str
    plan: str | None = None
    plan_title: str | None = None
    period_days: int | None = None
    price: float | None = None
    active: bool
    # Конец текущего периода. Общий конец доступа, вместе с очередью ещё не
    # начавшихся периодов, — в expires_total_at.
    expires_at: dt.datetime | None = None
    days_left: int | None = None
    expires_total_at: dt.datetime | None = None
    upcoming: list[UpcomingOut] = []
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

    def key_out(key: "services.ios.IosKey") -> IosKeyOut:
        return IosKeyOut(
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
            disconnected=key.disconnected,
        )

    everything = services.ios.keys(user, include_disconnected=True)
    keys = [key_out(k) for k in everything if k.is_active]
    off = [key_out(k) for k in everything if not k.is_active and k.disconnected]

    notice = None
    if not keys and not off:
        if not user.has_access(now):
            notice = "Ключи отключены: подписка кончилась или закрыт доступ."
        else:
            notice = "Готовим ключи, это займёт около минуты — обновите страницу."

    # Ключей у человека столько, сколько номеров, а не строк: на каждый
    # номер приходится по ссылке на каждую страну. Отключённые тоже в счёте:
    # слот занят, пока ключ не удалён.
    used = len({key.slot for key in keys} | {key.slot for key in off})
    return IosOut(
        available=True,
        keys=keys,
        disconnected_keys=off,
        max_keys=IOS_MAX_KEYS,
        keys_count=used,
        can_add=user.has_access(now) and services.ios.free_slot(user) is not None,
        guide_url=settings().guide_link,
        notice=notice,
    )


def _ios_device_rows(user: User, now: dt.datetime) -> list[DeviceOut]:
    """
    Ключи AmneziaVPN в списке «Подключённые устройства».

    Ключ становится устройством по первому рукопожатию: сам факт выдачи —
    ещё не устройство (ссылку могли даже не вставить), а ключ, через
    который пошёл трафик, — уже оно, и место в списке занимает наравне с
    телефоном с приложением. Пропадает строка вместе с пиром: «отключить»
    в кабинете, снятие по концу подписки — и появляется снова с первым
    рукопожатием после включения.

    Строка одна на ключ, а не на пир: пиры одного слота на разных странах —
    это один iPhone, и рукопожатие берётся самое свежее из них.
    """
    by_slot: dict[int, list] = {}
    for key in user.keys:
        number = ios_slot_number(key.device_id)
        if number > 0 and key.revoked_at is None:
            by_slot.setdefault(number, []).append(key)

    rows: list[DeviceOut] = []
    for number, slot_keys in sorted(by_slot.items()):
        stamps = [k.last_handshake_at for k in slot_keys if k.last_handshake_at is not None]
        if not stamps:
            continue
        last = max(stamps)
        rows.append(
            DeviceOut(
                id=-number,
                kind="ios_key",
                slot=number,
                platform="amnezia",
                last_seen_at=last,
                created_at=min(k.created_at for k in slot_keys),
                is_connected=last > now - HANDSHAKE_WINDOW,
            )
        )
    return rows


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

    # Приложения и ключи AmneziaVPN в одном списке: и то и другое — место в
    # лимите тарифа, и человек должен видеть, что iPhone с вставленным
    # ключом занимает его так же, как телефон с приложением.
    devices = [
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
        for session in user.device_sessions(now)
    ] + _ios_device_rows(user, now)
    devices.sort(key=lambda d: d.last_seen_at, reverse=True)

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
        # «Действует до» и «осталось» — по общему концу доступа, а не по
        # текущему периоду: продление, встающее в очередь, обязано увеличивать
        # эти числа сразу, иначе кабинет и панель показывают старый срок.
        expires_at=user.access_expires_at(now),
        days_left=user.access_days_left(now),
        expires_total_at=user.access_expires_at(now),
        upcoming=[
            UpcomingOut(
                plan=s.plan,
                plan_title=s.plan_ref.name if s.plan_ref else s.plan,
                starts_at=s.starts_at,
                expires_at=s.expires_at,
                period_days=s.period_days,
            )
            for s in user.upcoming_subscriptions(now)
        ],
        device_limit=user.device_limit(now),
        # Приложения и ключи AmneziaVPN; вкладка браузера, из которой человек
        # читает эту самую страницу, устройством не является: туннеля в ней
        # нет, отключать нечего, а место в лимите тарифа она занимала.
        devices=devices,
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


@router.post("/account/ios/keys/{slot}/disconnect", response_model=AccountOut)
def disconnect_ios_key(
    slot: int,
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    """
    «Отключить» на строке ключа в «Подключённых устройствах».

    Пир уходит с узла, туннель на том iPhone падает сразу — как у
    устройства с приложением. Ссылка при этом остаётся за учёткой:
    «включить» вернёт ту же самую, и после подключения строка снова
    появится в устройствах. Насовсем ссылку убирает удаление ключа.
    """
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    try:
        problems = services.ios.disconnect_key(db, user, slot)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_off_failed"}
        ) from exc

    for problem in problems:
        # Узел не ответил — пир снимет сверка; человеку доступ уже закрыт.
        log.warning("отключение ключа %s у %s: %s", slot, user.public_id, problem)
    return _account_out(db, user, session)


@router.post("/account/ios/keys/{slot}/enable", response_model=AccountOut)
def enable_ios_key(
    slot: int,
    response: Response,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> AccountOut:
    """
    Включает отключённый ключ: тот же пир, та же ссылка.

    Человеку не нужно ничего переустанавливать — ссылка, вставленная в
    Amnezia, оживает как была. Отключение администратора так не снимается:
    оно про другое и снимается только из панели.
    """
    user, session = who
    response.headers["Cache-Control"] = "no-store"

    if user.ios_blocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "ключ отключён — напишите в поддержку",
            headers={"X-Error-Code": "ios_blocked"},
        )

    try:
        warnings = services.ios.reconnect_key(db, user, slot)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "ios_on_failed"}
        ) from exc

    for warning in warnings:
        log.warning("включение ключа %s у %s: %s", slot, user.public_id, warning)
    return _account_out(db, user, session)


# --- сброс пароля -------------------------------------------------------------


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetIn(BaseModel):
    token: str = Field(min_length=8, max_length=256)
    password: str = Field(min_length=8, max_length=128)


class ResetCheckOut(BaseModel):
    valid: bool
    login: str | None = None


@router.post("/password/forgot")
def password_forgot(
    body: ForgotIn, request: Request, db: OrmSession = Depends(get_db)
) -> dict[str, object]:
    """
    «Забыли пароль» — отправляет ссылку на почту.

    Ответ ВСЕГДА одинаковый, даже когда такой почты у нас нет. Иначе форма
    превращается в проверялку «зарегистрирован ли человек в этом сервисе», а
    это чужая приватность: спросить можно про любой чужой адрес.

    Частота ограничена по адресу отправителя: без этого форму используют,
    чтобы завалить чужой ящик письмами от нашего имени.
    """
    ip = client_ip(request)
    verdict = services.ratelimit.hit(
        db, f"forgot:{ip}", limit=5, window_minutes=60, lock_minutes=60
    )
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "слишком много попыток — попробуйте через час",
            headers={"Retry-After": str(verdict.retry_after or 3600)},
        )

    address = normalize_email(body.email)
    try:
        services.passwords.request(db, address, ip=ip)
    except Exception:  # pragma: no cover
        # Молчим наружу и здесь: сорвавшаяся отправка не повод рассказать,
        # что адрес существует.
        log.exception("сброс пароля: не удалось подготовить письмо")

    return {"ok": True}


@router.get("/password/reset/{token}", response_model=ResetCheckOut)
def password_reset_check(token: str, db: OrmSession = Depends(get_db)) -> ResetCheckOut:
    """
    Годна ли ссылка — чтобы страница сразу сказала «просрочена», а не после
    того, как человек придумает и введёт новый пароль.
    """
    entry = services.passwords.find(db, token)
    if entry is None:
        return ResetCheckOut(valid=False)
    return ResetCheckOut(valid=True, login=entry.user.login)


@router.post("/password/reset")
def password_reset(body: ResetIn, db: OrmSession = Depends(get_db)) -> dict[str, object]:
    """
    Смена пароля по ссылке.

    Все живые входы при этом гаснут. Это не побочный эффект: пароль меняют,
    когда старый мог утечь, и оставить работающими прежние сессии значит не
    сменить ничего.
    """
    try:
        user = services.passwords.apply(db, body.token, body.password)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers={"X-Error-Code": "reset_failed"}
        ) from exc
    return {"ok": True, "login": user.login}


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

    plan_code = body.plan_code
    if not plan_code:
        subscription = user.active_subscription()
        plan_code = subscription.plan if subscription else None
    if not plan_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "выберите тариф")

    try:
        # Заказ привязан к учётке, а не к почте: продление не должно
        # требовать почту, если человеку хватает кабинета и Telegram.
        order = services.create_order_for_user(
            db,
            user,
            plan_code=plan_code,
            origin="site",
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


# --- автопродление ------------------------------------------------------------


class RecurringPlanOut(BaseModel):
    """Тариф, на который можно подключить автосписание."""

    code: str
    title: str
    amount_kopecks: int
    currency: str
    interval: str  # month | year


class RecurringOut(BaseModel):
    """
    Автосписание глазами кабинета.

    `subscription` пуст, когда подключать ещё нечего или уже нечего, — тогда
    кабинет показывает предложение из `available`.
    """

    status: str | None = None
    plan_code: str | None = None
    plan_title: str | None = None
    amount_kopecks: int | None = None
    currency: str | None = None
    interval: str | None = None
    next_charge_at: dt.datetime | None = None
    last_charge_error: str | None = None
    # Ссылка на привязку счёта — только пока подписка ждёт подтверждения.
    redirect_url: str | None = None
    available: list[RecurringPlanOut] = []


def _recurring_out(db: OrmSession, user: User) -> RecurringOut:
    sub = services.recurring.get_live(db, user)
    plans_by_code = {plan.code: plan for plan in services.site_plans(db)}
    available = [
        RecurringPlanOut(
            code=plan.code,
            title=plan.name,
            amount_kopecks=plan.price_kopecks,
            currency=plan.currency,
            interval=services.recurring.plan_interval(plan) or "month",
        )
        for plan in services.recurring.eligible_plans(db)
    ]
    if sub is None:
        return RecurringOut(available=available)
    plan = plans_by_code.get(sub.plan_code)
    return RecurringOut(
        status=sub.status,
        plan_code=sub.plan_code,
        plan_title=plan.name if plan else sub.plan_code,
        amount_kopecks=sub.amount_kopecks,
        currency=sub.currency,
        interval=sub.interval,
        next_charge_at=sub.next_charge_at,
        last_charge_error=sub.last_charge_error,
        redirect_url=sub.redirect_url if sub.status == "pending" else None,
        available=available,
    )


@router.get("/account/recurring", response_model=RecurringOut)
def recurring_status(
    who: tuple[User, Session] = Depends(current_user), db: OrmSession = Depends(get_db)
) -> RecurringOut:
    user, _ = who
    return _recurring_out(db, user)


class RecurringIn(BaseModel):
    plan_code: str


@router.post("/account/recurring", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
def recurring_create(
    body: RecurringIn,
    who: tuple[User, Session] = Depends(current_user),
    db: OrmSession = Depends(get_db),
) -> RecurringOut:
    user, _ = who
    try:
        sub = services.recurring.create(db, user, body.plan_code, origin="site")
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    out = _recurring_out(db, user)
    # Свежесозданной подписке ссылка нужна сразу — человек уходит по ней.
    out.redirect_url = sub.redirect_url
    return out


@router.post("/account/recurring/cancel", response_model=RecurringOut)
def recurring_cancel(
    who: tuple[User, Session] = Depends(current_user), db: OrmSession = Depends(get_db)
) -> RecurringOut:
    user, _ = who
    sub = services.recurring.get_live(db, user)
    if sub is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "автосписание не подключено")
    try:
        services.recurring.cancel(db, sub)
    except services.PanelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _recurring_out(db, user)


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
