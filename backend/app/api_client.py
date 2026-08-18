"""
API для приложений: вход по логину и паролю, список серверов с конфигами.

Список серверов отдаётся целиком при каждом запросе, поэтому добавленный
в панели сервер появляется у всех при следующем открытии приложения —
раздавать его вручную не нужно.

Наружу не уходит ничего, что приложению нечего показывать: ни адреса
сервера, ни публичного ключа, ни выданного адреса в подсети. Остаётся
страна с городом — то, из чего человек выбирает, — и сам конфиг, который
приложение отдаёт туннелю, но не рисует на экране.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from . import geo, services
from .config import settings
from .db import get_db
from .models import Provisioning, Session, User, is_ios_slot
from .provisioning import config_for
from .security import client_ip

log = logging.getLogger("panel.client")

router = APIRouter(prefix="/api/v1", tags=["client"])


def _error_code_header(exc: services.PanelError) -> dict[str, str] | None:
    """
    Код причины отказа рядом с текстом.

    Заголовком, а не полем в теле: `detail` приложения читают строкой уже
    сейчас, и превращать его в объект — значит сломать вход всем, кто ещё
    не обновился.
    """
    code = getattr(exc, "code", "")
    return {"X-Error-Code": code} if code else None


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    # Постоянный идентификатор установки. Нужен, чтобы лимит устройств
    # считал переустановку приложения тем же телефоном, а не вторым.
    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=96)


class ServerOut(BaseModel):
    """
    Точка подключения глазами приложения.

    `config` — единственное техническое поле: его отдают туннелю как есть.
    Показывать его пользователю нельзя, и показывать нечего — всё, что
    нужно на экране, лежит в стране и городе.
    """

    id: int
    name: str
    country: str | None = None
    country_en: str | None = None
    city: str | None = None
    city_en: str | None = None
    country_code: str | None = None
    config: str


class SubscriptionOut(BaseModel):
    active: bool
    plan: str | None = None
    expires_at: dt.datetime | None = None
    days_left: int | None = None
    # Трафик в байтах: лимит None — безлимит.
    traffic_used_bytes: int = 0
    traffic_limit_bytes: int | None = None

    # Остаток трафика. None — безлимит. Считает сервер, а не приложение:
    # вычитание в клиенте однажды разойдётся с тем, по чему реально
    # закрывается доступ.
    traffic_left_bytes: int | None = None
    # Осталось меньше десятой части лимита — приложению пора предупредить.
    traffic_low: bool = False

    # Подписка кончается в ближайшие дни: приложению пора показать кнопку
    # продления. Порог задаёт сервер, чтобы менять его без пересборки
    # приложений на четырёх платформах.
    expires_soon: bool = False
    renew_url: str | None = None


class AccountOut(BaseModel):
    public_id: str
    login: str
    name: str | None = None


class LoginResponse(BaseModel):
    token: str
    expires_at: dt.datetime
    account: AccountOut
    subscription: SubscriptionOut
    servers: list[ServerOut]
    # Почему список пуст. Пустой массив без объяснения — худшее, что может
    # показать приложение: человек ввёл логин с паролем, вошёл, и дальше
    # тишина. См. _notice_for.
    notice: str | None = None


class ServersResponse(BaseModel):
    subscription: SubscriptionOut
    servers: list[ServerOut]
    notice: str | None = None


def current_session(
    authorization: str | None = Header(default=None),
    db: OrmSession = Depends(get_db),
) -> Session:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен токен")
    session = services.session_for_token(db, authorization.split(" ", 1)[1].strip())
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен недействителен")
    return session


# Верхняя планка порога «трафика осталось мало».
#
# Сам порог считает _traffic_low_threshold: он подстраивается под лимит.
# Абсолютные пять гигабайт на любом тарифе не работали: при лимите в
# гигабайт предупреждение горело с первой секунды — человеку писали
# «осталось мало: 1020 МБ», когда он израсходовал четыре мегабайта.
TRAFFIC_LOW_CAP_BYTES = 5 * 1024**3

# За сколько дней до конца подписки приложение показывает кнопку продления.
EXPIRES_SOON_DAYS = 3


def _traffic_low_threshold(limit: int) -> int:
    """
    Когда включать «трафика осталось мало»: за пятую часть лимита, но не
    больше пяти гигабайт.

    Пятая часть — это ещё заметный запас, чтобы успеть продлить. Планка
    сверху нужна большим тарифам: на 250 ГБ пятая часть — 50 ГБ, и пугать
    человека за пятьдесят гигабайт до конца бессмысленно, там хватает пяти.
    """
    return min(TRAFFIC_LOW_CAP_BYTES, limit // 5)


def _subscription_out(user: User) -> SubscriptionOut:
    sub = user.active_subscription()
    limit = user.effective_traffic_limit()
    used = user.traffic_used_bytes

    left_bytes = max(0, limit - used) if limit is not None else None
    traffic_low = left_bytes is not None and left_bytes <= _traffic_low_threshold(limit)
    exhausted = left_bytes == 0

    if sub is None:
        return SubscriptionOut(
            active=False,
            traffic_used_bytes=used,
            traffic_limit_bytes=limit,
            traffic_left_bytes=left_bytes,
            traffic_low=traffic_low,
            # Подписки нет вовсе — продление нужно тем более.
            expires_soon=True,
            renew_url=_renew_url(),
        )

    days_left = max(0, (sub.expires_at - services.utcnow()).days)
    expires_soon = days_left <= EXPIRES_SOON_DAYS

    return SubscriptionOut(
        active=True,
        plan=sub.plan,
        expires_at=sub.expires_at,
        days_left=days_left,
        traffic_used_bytes=used,
        traffic_limit_bytes=limit,
        traffic_left_bytes=left_bytes,
        traffic_low=traffic_low,
        expires_soon=expires_soon,
        # Кнопка продления нужна не только под конец срока: предупреждение о
        # кончающемся трафике без неё — тупик, человеку некуда нажать.
        renew_url=_renew_url() if expires_soon or traffic_low or exhausted else None,
    )


def _renew_url() -> str:
    """
    Куда приложение отправляет человека продлевать.

    В личный кабинет, а не сразу на оплату: там он войдёт теми же логином и
    паролем, увидит свой тариф и срок и нажмёт «Продлить». Ссылка прямо на
    платёжную форму потребовала бы заводить заказ до того, как человек
    вообще решил платить.
    """
    return f"{settings().site_url.rstrip('/')}/account.html"


def _provision_missing_keys(user_id: int, device_id: str) -> None:
    """
    Досоздаёт недостающие ключи в фоне, уже после ответа приложению.

    Раньше это делалось прямо в запросе, и вход занимал столько, сколько
    тупит самый медленный сервер: недоступный узел добавляет секунды
    ожидания на каждого. Ключи обычно уже есть — их выдают при входе, — а
    те, что появились из-за нового сервера, подтянутся к следующему запросу
    списка.

    Устройство одно, своё: досоздавать пиры соседним телефонам того же
    человека по запросу с этого — лишние заходы по SSH за чужой доступ,
    который и так появится при их собственном входе.
    """
    from .db import SessionLocal

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.has_access():
            return
        # Устройство могли отвязать, пока задача ждала очереди: disconnect
        # погасил сессию и отозвал ключи, а мы бы тут же завели пир заново —
        # отключённый телефон (украденный, чужой) вернулся бы в VPN. Заводим
        # ключ, только если у устройства ещё есть живая сессия.
        if device_id not in user.devices():
            log.info("фоновая выдача пропущена: устройство %s уже отвязано", device_id or "(учётки)")
            return
        services.ensure_keys(db, user, devices={device_id})


def _notice_for(db: OrmSession, user: User, servers: list[ServerOut]) -> str | None:
    """
    Почему приложению нечего показать.

    Пустой список без объяснения — это и был весь баг: человек оплачивал,
    вводил логин с паролем, входил успешно и упирался в пустой экран. Ни
    приложение, ни панель не могли сказать, в чём дело, потому что API
    отдавал `[]` и не отдавал причины.

    Текст пишется для человека и показывается им как есть, поэтому он
    объясняет, что делать, а не что сломалось внутри.
    """
    if servers:
        return None

    if user.is_blocked:
        return "Доступ заблокирован. Напишите в поддержку."
    if not user.is_active:
        return "Доступ приостановлен. Напишите в поддержку."

    if user.active_subscription() is None:
        return "Подписка закончилась. Продлите её в личном кабинете на сайте."
    if user.traffic_exhausted():
        return "Закончился трафик по тарифу. Он обновится при продлении подписки."

    active = services.active_servers(db)
    if not active:
        # Ни одного включённого узла. Это не проблема клиента: сервис не
        # доделан или узлы выключены администратором.
        return "Серверы временно недоступны. Мы уже занимаемся этим — попробуйте позже."

    if not any(services.can_serve(server) for server in active):
        # Узлы есть, но выдать с них нечего: нет шаблона, нет общего ключа
        # либо адрес демонстрационный. Клиенту знать подробности незачем.
        return "Серверы настраиваются. Попробуйте через несколько минут."

    # Узлы рабочие, а конфига именно для этого человека ещё нет — обычно так
    # выглядят первые секунды после оплаты, пока пиры создаются в фоне.
    return "Готовим подключение, это займёт около минуты. Потяните экран, чтобы обновить."


def _servers_out(
    db: OrmSession,
    user: User,
    session: Session | None = None,
    background: BackgroundTasks | None = None,
) -> list[ServerOut]:
    """
    Серверы, доступные этому устройству прямо сейчас.

    Без действующей подписки список пустой: платящий и неплатящий не должны
    получать одно и то же.

    Конфиг берётся по устройству, а не по учётке: у каждого свой пир, и
    отдать телефону конфиг ноутбука значит вернуть ровно ту общую пару
    ключей, из-за которой отключение одного устройства было невозможно.
    """
    if not user.has_access():
        return []

    device_id = session.device_key if session is not None else ""
    by_server: dict[int, object] = {}
    shared: dict[int, object] = {}
    for key in user.keys:
        if key.revoked_at is None:
            # Слоты `ios-N` — ключи для AmneziaVPN на iPhone, у них своя
            # раздача через кабинет. Приложению они не принадлежат: отдать
            # ему чужой пир значит поделить один адрес в подсети на двоих.
            if is_ios_slot(key.device_id):
                continue
            if (key.device_id or "") == device_id:
                by_server[key.server_id] = key
            elif not key.device_id:
                shared[key.server_id] = key

    # Чего-то не хватает — досоздадим после ответа, не задерживая человека.
    # Считаем по своим ключам, до подмены общим: иначе устройство, которому
    # отдали ключ учётки, выглядело бы обеспеченным и своего пира не
    # получило бы никогда.
    if background is not None:
        missing = any(
            server.id not in by_server and server.provisioning != Provisioning.SHARED
            for server in services.active_servers(db)
        )
        if missing:
            background.add_task(_provision_missing_keys, user.id, device_id)

    # Своего пира ещё нет — отдаём общий ключ учётки.
    #
    # Иначе устройство, вошедшее до того, как появились пиры на устройство,
    # получало бы пустой список стран и роняло рабочий туннель: свой ключ
    # создаётся в фоне и поспевает к следующему опросу, а этот ответ уже
    # ушёл. Подмена не мешает — общий пир на узле живой, конфиг рабочий, —
    # а со следующего запроса устройство перейдёт на собственный.
    for server_id, key in shared.items():
        by_server.setdefault(server_id, key)

    out: list[ServerOut] = []
    for server in services.active_servers(db):
        if services.diagnostics.is_documentation_address(server.host):
            # Адрес из диапазона для примеров в документации — подключаться
            # там не к чему. Такой узел попадает в базу только из
            # демонстрационных данных, и отдать его клиенту хуже, чем не
            # отдать ничего: он увидит страну в списке, нажмёт «подключиться»
            # и получит вечное ожидание вместо понятной ошибки.
            log.warning(
                "сервер «%s» пропущен: адрес %s из документационного диапазона",
                server.name,
                server.host,
            )
            continue

        config = config_for(server, by_server.get(server.id))
        if not config:
            # Сервер есть, но конфига для этого человека пока нет —
            # показывать его в приложении нельзя: подключение упадёт.
            continue
        out.append(
            ServerOut(
                id=server.id,
                # Имя для списка — страна, а не внутреннее название сервера:
                # «Нидерланды» человеку понятнее, чем «nl-ams-01».
                name=server.country or server.name,
                country=server.country,
                # Английское название достаём по коду страны, если своего в
                # панели не завели. Иначе приложение с английским интерфейсом
                # честно откатывалось на русское, и человек видел кириллицу в
                # списке стран. Заполненное вручную поле важнее справочника:
                # у администратора могут быть свои причины назвать иначе.
                country_en=server.country_en or geo.country_en(server.country_code, server.country),
                city=server.city,
                # Города в справочнике нет — их тысячи, и надёжного
                # соответствия по коду не построить. Пустое английское
                # название города откатывается на русское: показать
                # «Амстердам» англичанину лучше, чем пустую строку под
                # названием страны.
                city_en=server.city_en or server.city,
                country_code=server.country_code,
                config=config,
            )
        )
    return out


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    background: BackgroundTasks,
    db: OrmSession = Depends(get_db),
) -> LoginResponse:
    try:
        user, token = services.authenticate(
            db,
            login=body.login,
            password=body.password,
            platform=body.platform,
            app_version=body.app_version,
            ip=client_ip(request),
            device_id=body.device_id,
            device_name=body.device_name,
        )
    except services.LoginThrottled as exc:
        # 429, а не 401: приложению нужно понять, что дело не в пароле, и
        # не предлагать человеку набрать его ещё раз прямо сейчас.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            # Сколько ждать, приложение берёт из Retry-After — это уже
            # стандартный заголовок, своего для этого заводить незачем.
            headers={"Retry-After": str(exc.retry_after), "X-Error-Code": "throttled"},
        ) from exc
    except services.PanelError as exc:
        # Текст здесь русский, а интерфейс приложения бывает английским.
        # Поэтому рядом с ним — код причины: по нему приложение подставит
        # свой перевод, а старое, кода не знающее, покажет текст как раньше.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(exc), headers=_error_code_header(exc)
        ) from exc

    session = services.session_for_token(db, token)
    assert session is not None
    _provision_for_login(db, user, session)
    servers = _servers_out(db, user, session, background)
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
    )


# Сколько вход готов ждать выдачу пира новому устройству. Не «сколько
# нужно», а «сколько человек стерпит»: не успели — список приедет следующим
# запросом, о чём приложению скажет notice.
LOGIN_PROVISION_SECONDS = 8


def _provision_for_login(db: OrmSession, user: User, session: Session) -> None:
    """
    Заводит пира этому устройству прямо во время входа.

    В фоне это делать нельзя: у нового устройства своего пира ещё нет, и
    ответ на вход оказался бы пустым списком стран — человек ввёл логин с
    паролем и упёрся в «серверов нет». Знакомому устройству эта проверка
    ничего не стоит: ключ уже есть, до SSH дело не доходит.
    """
    if not user.has_access() or not session.is_device:
        return
    warnings = services.ensure_keys(
        db,
        user,
        devices={session.device_key},
        deadline=time.monotonic() + LOGIN_PROVISION_SECONDS,
    )
    for warning in warnings:
        log.warning("вход %s: %s", user.public_id, warning)

    # Сбрасываем кэш коллекции ключей. ensure_keys добавил новые UserKey
    # через db.add по внешнему ключу, не трогая уже загруженный user.keys, а
    # сессия живёт с expire_on_commit=False — коммит внутри ensure_keys эту
    # коллекцию не перечитывает. Без сброса _servers_out ниже итерирует
    # старый список без только что созданного пира и отдаёт устройству
    # пустой список стран — на самом входе, ровно когда пир уже готов.
    db.expire(user, ["keys"])


class RegisterRequest(BaseModel):
    """
    Регистрация с сайта.

    Пароль длиннее, чем требует вход: там его выдаёт панель и он заведомо
    стойкий, а здесь человек придумывает сам.
    """

    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=254)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=96)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    request: Request,
    background: BackgroundTasks,
    db: OrmSession = Depends(get_db),
) -> LoginResponse:
    """
    Заводит учётку и сразу пускает внутрь.

    Отвечает тем же, чем вход: сайту и приложению после регистрации не нужен
    второй запрос, а человеку — второй ввод тех же логина и пароля.

    Тариф — пробный, из настроек. Оплаченные учётки по-прежнему создаёт
    только вебхук платёжного провайдера: бесплатной регистрацией нельзя
    получить то, за что платят.
    """
    config = settings()
    if not config.signup_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "регистрация сейчас закрыта",
            headers={"X-Error-Code": "signup_closed"},
        )

    ip = client_ip(request)
    verdict = services.ratelimit.hit(
        db,
        f"signup:{ip or 'unknown'}",
        limit=config.signup_max_per_ip,
        window_minutes=config.signup_window_minutes,
        lock_minutes=config.signup_window_minutes,
    )
    if not verdict.allowed:
        log.warning("регистрация заперта для %s", ip)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "с этого адреса уже заводили аккаунты — попробуйте позже",
            headers={"Retry-After": str(verdict.retry_after), "X-Error-Code": "throttled"},
        )

    try:
        user, _password, _warnings = services.create_user(
            db,
            login=body.login,
            password=body.password,
            plan_code=config.signup_plan_code,
            email=body.email,
            note="регистрация с сайта",
        )
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc), headers=_error_code_header(exc)
        ) from exc

    # Снимаем замок входа с только что заведённого логина.
    #
    # Человек мог несколько раз попытаться войти этим логином ДО регистрации,
    # думая, что аккаунт есть, — и запереть бакет login-throttle на пятнадцать
    # минут. Тогда authenticate ниже упирался в LoginThrottled уже ПОСЛЕ того,
    # как create_user завёл учётку: 500, пользователь создан, токена нет, а
    # повтор жалуется «логин занят». Свой собственный, только что созданный
    # логин запирать бессмысленно — сбрасываем его счётчики.
    services.reset_login_throttle(db, body.login, ip)

    # Сессию открываем тем же кодом, что и обычный вход: там живут учёт
    # устройств, лимит по тарифу и запись в журнал.
    _user, token = services.authenticate(
        db,
        login=body.login,
        password=body.password,
        platform=body.platform,
        app_version=body.app_version,
        ip=ip,
        device_id=body.device_id,
        device_name=body.device_name,
    )
    session = services.session_for_token(db, token)
    assert session is not None
    _provision_for_login(db, user, session)
    servers = _servers_out(db, user, session, background)
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
    )


@router.get("/servers", response_model=ServersResponse)
def servers(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> ServersResponse:
    services.touch(db, session, client_ip(request))
    user = session.user
    servers = _servers_out(db, user, session, background)
    return ServersResponse(
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
    )


@router.post("/heartbeat")
def heartbeat(
    request: Request,
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    """Приложение отмечается, пока подключено — из этого видно живые сессии."""
    services.touch(db, session, client_ip(request))
    user = session.user
    return {"ok": True, "active": user.has_access(), "subscription": _subscription_out(user).model_dump()}


class UpdateOut(BaseModel):
    """Что приложение показывает на кнопке обновления."""

    update_available: bool
    version: str | None = None
    url: str | None = None
    changelog: str | None = None
    released_at: dt.datetime | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    # Обязательное обновление: без него сервис не работает.
    mandatory: bool = False


@router.get("/version", response_model=UpdateOut)
def version(
    platform: str,
    current: str | None = None,
    db: OrmSession = Depends(get_db),
) -> UpdateOut:
    """
    Есть ли версия новее установленной.

    Без токена: приложение спрашивает это и на экране входа, когда сессии
    ещё нет, а обязательное обновление должно дойти и до тех, кто не вошёл.
    """
    return UpdateOut(**services.check_update(db, platform, current))


@router.post("/logout")
def logout(
    session: Session = Depends(current_session), db: OrmSession = Depends(get_db)
) -> dict[str, bool]:
    session.revoked_at = services.utcnow()
    db.commit()
    return {"ok": True}
