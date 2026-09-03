from __future__ import annotations

import datetime as dt
import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import geo, provisioning, services
from .config import settings
from .db import get_db
from .models import (
    NodeEndpoint,
    Provisioning,
    Server,
    Session,
    User,
    UserKey,
    is_external_slot,
    is_ios_slot,
    utcnow,
    Order,
)
from .provisioning import serving_config
from .security import client_ip, ip_tag

log = logging.getLogger("panel.client")

router = APIRouter(prefix="/api/v1", tags=["client"])


def _error_code_header(exc: services.PanelError) -> dict[str, str] | None:
    code = getattr(exc, "code", "")
    return {"X-Error-Code": code} if code else None


class LoginRequest(BaseModel):

    # Вход из мини-приложения: подпись Telegram привязывает учётку,
    # чтобы следующий запуск открывался сразу.
    init_data: str | None = Field(default=None, max_length=8192)
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=96)


class VlessOut(BaseModel):
    """
    Второй путь до того же узла — VLESS поверх Reality.

    Нужен там, где AmneziaWG не проходит вовсе: он идёт по TCP на 443 и от
    настоящего HTTPS к донорскому сайту неотличим. Поля разложены по одному,
    а не только ссылкой, чтобы клиенту не пришлось разбирать `vless://`
    самому; ссылка тоже есть — её удобно отдать человеку для стороннего
    приложения.
    """

    host: str
    port: int
    id: str
    public_key: str
    short_id: str = ""
    server_name: str = ""
    fingerprint: str = "chrome"
    flow: str = ""
    url: str = ""


class ServerOut(BaseModel):

    id: int
    name: str
    country: str | None = None
    country_en: str | None = None
    city: str | None = None
    city_en: str | None = None
    country_code: str | None = None
    config: str
    alt_ports: list[int] = []
    # Пусто, если на узле нет живой точки Reality или её не удалось выдать:
    # отсутствие запасного пути не повод не отдать основной.
    vless: VlessOut | None = None


class SubscriptionOut(BaseModel):
    active: bool
    plan: str | None = None
    expires_at: dt.datetime | None = None
    days_left: int | None = None
    traffic_used_bytes: int = 0
    traffic_limit_bytes: int | None = None

    traffic_left_bytes: int | None = None
    traffic_low: bool = False

    expires_soon: bool = False
    renew_url: str | None = None


class AccountOut(BaseModel):
    public_id: str
    login: str
    name: str | None = None
    # Заполнен ровно один раз: в ответе на регистрацию через Telegram, где
    # пароль придумали за человека. Витрина обязана показать его сразу —
    # второй раз узнать пароль будет неоткуда.
    password: str | None = None


class LoginResponse(BaseModel):
    token: str
    expires_at: dt.datetime
    account: AccountOut
    subscription: SubscriptionOut
    servers: list[ServerOut]
    subscription_url: str | None = None
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


TRAFFIC_LOW_CAP_BYTES = 5 * 1024**3

EXPIRES_SOON_DAYS = 3


def _traffic_low_threshold(limit: int) -> int:
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
            expires_soon=True,
            renew_url=_renew_url(),
        )

    # Считаем по всей цепочке подписок, а не по текущей: после пробных
    # двух дней в очереди могут стоять подаренные две недели, и «остался
    # 1 день» с кнопкой продления — неправда. Дата — «как если бы
    # разморозили сейчас»: у замороженного в базе лежит уже прошедший
    # срок, показывать его нельзя.
    days_left = user.access_days_left_display() or 0
    expires_soon = days_left <= EXPIRES_SOON_DAYS

    return SubscriptionOut(
        active=True,
        plan=sub.plan,
        expires_at=user.access_ends_if_resumed() or sub.expires_at,
        days_left=days_left,
        traffic_used_bytes=used,
        traffic_limit_bytes=limit,
        traffic_left_bytes=left_bytes,
        traffic_low=traffic_low,
        expires_soon=expires_soon,
        renew_url=_renew_url() if expires_soon or traffic_low or exhausted else None,
    )


def _renew_url() -> str:
    return f"{settings().site_url.rstrip('/')}/account"


def _subscription_url(db: OrmSession, session: Session) -> str | None:
    if not session.is_device:
        return None
    return services.subscription.url_for(services.subscription.mint_for_session(db, session))


def _provision_missing_keys(user_id: int, device_id: str, awg_level: int = 1) -> None:
    from .db import SessionLocal

    services.compat.CLIENT_AWG_LEVEL.set(awg_level)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.has_access():
            return
        if device_id and device_id not in user.devices():
            log.info("фоновая выдача пропущена: устройство %s уже отвязано", device_id)
            return
        services.ensure_keys(db, user, devices={device_id})


def _notice_for(db: OrmSession, user: User, servers: list[ServerOut]) -> str | None:
    if servers:
        return None

    if user.is_blocked:
        return "Доступ заблокирован. Напишите в поддержку."
    if not user.is_active:
        return "Доступ приостановлен. Напишите в поддержку."
    # Пауза человек поставил сам, поэтому и текст другой: не «напишите в
    # поддержку», а «снимите паузу» — снять её он может там же, где ставил.
    if user.is_frozen:
        return "Подписка на паузе — дни не тратятся. Снимите паузу в личном кабинете или в Telegram-боте."

    if user.active_subscription() is None:
        return "Подписка закончилась. Продлите её в личном кабинете на сайте."
    if user.traffic_exhausted():
        return "Закончился трафик по тарифу. Он обновится при продлении подписки."

    active = services.active_servers(db)
    if not active:
        return "Серверы временно недоступны. Мы уже занимаемся этим — попробуйте позже."

    if not any(services.can_serve(server) for server in active):
        return "Серверы настраиваются. Попробуйте через несколько минут."

    return "Готовим подключение, это займёт около минуты. Потяните экран, чтобы обновить."


def _serve_targets(
    db: OrmSession,
    user: User,
    device_id: str,
    background: BackgroundTasks | None = None,
) -> list[tuple[Server, UserKey | None]]:
    if not user.has_access():
        return []

    device_id = device_id or ""
    by_server: dict[int, UserKey] = {}
    shared: dict[int, UserKey] = {}
    for key in user.keys:
        if key.revoked_at is None:
            if is_ios_slot(key.device_id):
                continue
            if (key.device_id or "") == device_id:
                by_server[key.server_id] = key
            elif not key.device_id:
                shared[key.server_id] = key

    # Ссылка, выпущенная руками (ext-N), своих ключей не имеет и живёт общим
    # ключом учётки: недостающие ключи для неё заводим общие, иначе узел,
    # добавленный после выпуска ссылки, в подписке так и не появится.
    external = is_external_slot(device_id)
    if external:
        for server_id, key in shared.items():
            by_server.setdefault(server_id, key)

    if background is not None:
        missing = any(
            server.id not in by_server and server.provisioning != Provisioning.SHARED
            for server in services.active_servers(db)
        )
        if missing:
            background.add_task(
                _provision_missing_keys,
                user.id,
                "" if external else device_id,
                services.compat.CLIENT_AWG_LEVEL.get(),
            )

    if not external:
        for server_id, key in shared.items():
            by_server.setdefault(server_id, key)

    targets: list[tuple[Server, UserKey | None]] = []
    for server in services.active_servers(db):
        if services.diagnostics.is_documentation_address(server.host):
            log.warning(
                "сервер «%s» пропущен: адрес %s из документационного диапазона",
                server.name,
                server.host,
            )
            continue
        key = by_server.get(server.id)
        if key is not None:
            # И ключ устройства, и общий ключ учётки, которым живут подписки:
            # переезд на точку 2.0 — только если клиент её понимает и ключ
            # сейчас не подключён (см. keys.migrate_to_awg2).
            key = services.keys.migrate_awg(db, user, server, key)
        targets.append((server, key))
    return targets


def _servers_out(
    db: OrmSession,
    user: User,
    session: Session | None = None,
    background: BackgroundTasks | None = None,
) -> list[ServerOut]:
    device_id = session.device_key if session is not None else ""
    services.compat.CLIENT_AWG_LEVEL.set(
        services.compat.awg_level(session.platform, session.app_version) if session is not None else 0
    )
    out: list[ServerOut] = []
    for server, key in _serve_targets(db, user, device_id, background):
        config = serving_config(server, key)
        if not config:
            continue
        main_port, spare_ports = _ports_for(db, server, key)
        config = _with_chosen_port(db, server, key, config)
        config = _with_junk_for(db, session, server, key, config)
        out.append(
            ServerOut(
                id=server.id,
                name=server.country or server.name,
                country=server.country,
                country_en=server.country_en or geo.country_en(server.country_code, server.country),
                city=server.city,
                city_en=server.city_en or server.city,
                country_code=server.country_code,
                config=config,
                alt_ports=[main_port] + spare_ports,
                vless=_vless_out(db, user, server, device_id),
            )
        )
    return out


def _vless_out(
    db: OrmSession, user: User, server: Server, device_id: str
) -> VlessOut | None:
    """
    Готовит запасной путь до узла: доступ к Reality для этого устройства.

    Молчим при любой заминке. Reality — запасной ход, и если он не сложился,
    человек должен получить обычный конфиг, а не ошибку входа. Сессиям, что
    не занимают слот устройства (бот, сайт), запасной путь не нужен: они и
    основной ключ не получают.
    """
    if not device_id:
        return None
    try:
        from .models import EndpointKind
        from .services import xray

        live = [
            ep
            for ep in server.endpoints
            if ep.kind == EndpointKind.VLESS and ep.is_live and xray.is_on_node(ep)
        ]
        if not live:
            return None
        endpoint = sorted(live, key=lambda e: (e.priority, e.id))[0]

        creds = xray.live_creds(db, user, server, device_id)
        cred = next((c for c in creds if c.endpoint_id == endpoint.id), None)
        if cred is None:
            if not endpoint.accepts_new:
                return None
            cred = xray.issue_cred(db, user, server, endpoint, device_id)

        identity = cred.identity
        if not identity:
            return None

        params = endpoint.params or {}
        extra = cred.extra or {}
        names = params.get("server_names") or [""]
        return VlessOut(
            host=endpoint.public_host(server),
            port=params.get("advertise_port") or endpoint.listen_port,
            id=identity,
            public_key=params.get("public_key", ""),
            short_id=extra.get("short_id", ""),
            server_name=names[0],
            fingerprint=params.get("fingerprint", "chrome"),
            flow=extra.get("flow", ""),
            url=xray.share_link(endpoint, cred, server) or "",
        )
    except Exception:
        log.exception("сервер «%s»: запасной путь Reality не собрался", server.name)
        return None


PORT_PROBE_SECONDS = 180

PORT_PROBE_GRACE = dt.timedelta(minutes=10)


def _endpoint_for(db: OrmSession, server: Server, key: UserKey | None) -> NodeEndpoint | None:
    if key is None or key.endpoint_id is None:
        return None
    endpoint = db.get(NodeEndpoint, key.endpoint_id)
    if endpoint is None or endpoint.server_id != server.id:
        return None
    return endpoint


def _port_plan(
    db: OrmSession, server: Server, key: UserKey | None
) -> tuple[int, list[int], int]:
    """
    (главный порт, запасные по порядку перебора, порт, который слушает awg).

    Главный — тот, что назначен точке входа (advertise_port), а не тот, что
    слушает awg. 51820 — эталонный порт WireGuard, и у сотовых операторов
    он под шейпом: рукопожатие проходит, дальше растут потери. Поэтому он
    уходит в самый конец списка — клиент дойдёт до него, только когда
    промолчат все остальные. Объявленный порт обязан быть среди запасных:
    на узел он попадает NAT-редиректом, и порт «из головы» ушёл бы человеку
    в никуда.
    """
    endpoint = _endpoint_for(db, server, key)
    if endpoint is not None:
        listen, spares = endpoint.listen_port, endpoint.alt_port_list()
        raw = (endpoint.params or {}).get("advertise_port")
    else:
        listen, spares, raw = server.port, server.alt_port_list(), None

    try:
        advertised = int(raw) if raw else None
    except (TypeError, ValueError):
        advertised = None

    if advertised and advertised != listen and advertised in spares:
        return advertised, [p for p in spares if p != advertised] + [listen], listen
    return listen, spares, listen


def _ports_for(
    db: OrmSession, server: Server, key: UserKey | None
) -> tuple[int, list[int]]:
    main_port, spares, _listen = _port_plan(db, server, key)
    return main_port, spares


def _with_chosen_port(
    db: OrmSession, server: Server, key: UserKey | None, config: str
) -> str:
    main_port, ports, listen = _port_plan(db, server, key)
    if key is None or not ports:
        return config

    now = utcnow()
    if key.last_handshake_at is not None or now - key.created_at < PORT_PROBE_GRACE:
        chosen = key.endpoint_port or provisioning.endpoint_port(config) or main_port
        if chosen == listen and main_port != listen:
            # Ключ прилип к порту awg, пока у точки не было объявленного:
            # первое же рукопожатие на 51820 замораживало выбор навсегда,
            # хотя дальше связь шла с потерями. Переводим на объявленный;
            # у кого работает только 51820, приложение вернёт его само —
            # он остался в конце списка запасных.
            chosen = main_port
            if key.endpoint_port != chosen:
                key.endpoint_port = chosen
                db.commit()
        return provisioning.with_endpoint_port(config, chosen)

    # Колесо перебора для ключа, который ни разу не подключался. Порт awg в
    # него не входит, когда есть объявленный: попади он в конфиг, первое
    # удачное рукопожатие заморозило бы ключ на задушенном порту.
    wheel = [main_port] + [p for p in ports if p != listen or main_port == listen]
    index = int(now.timestamp() // PORT_PROBE_SECONDS) % len(wheel)
    chosen = wheel[index]
    if key.endpoint_port != chosen:
        key.endpoint_port = chosen
        db.commit()
    return provisioning.with_endpoint_port(config, chosen)


def _with_junk_for(
    db: OrmSession,
    session: Session | None,
    server: Server,
    key: UserKey | None,
    config: str,
) -> str:
    """
    Строки I1–I5 — только тем приложениям, которые их разбирают.

    Остальным — конфиг без них: старый движок отвергает незнакомый ключ
    целиком, и человек остался бы без связи из-за одного лишнего пакета.
    """
    endpoint = _endpoint_for(db, server, key)
    platform = session.platform if session is not None else None
    version = session.app_version if session is not None else None
    if endpoint is not None and services.compat.supports_special_junk(platform, version):
        return provisioning.with_special_junk(config, endpoint.params)
    return provisioning.without_special_junk(config)


def _adopt_by_orders(db: OrmSession, telegram_id: int) -> User | None:
    """
    Ищет учётку, заведённую когда-то по заказу с этого же Telegram.

    Берём только однозначный случай: все заказы этого telegram_id ведут в одну
    учётку, и та ещё ни к какому Telegram не привязана. Любая неоднозначность —
    отказ: молча подключить человека к чужому аккаунту хуже, чем завести новый.
    """
    rows = db.scalars(
        select(Order.user_id)
        .where(Order.telegram_id == telegram_id, Order.user_id.is_not(None))
        .distinct()
    ).all()
    ids = {row for row in rows if row}
    if len(ids) != 1:
        return None
    candidate = db.get(User, ids.pop())
    if candidate is None or candidate.telegram_id is not None:
        return None
    return candidate


def _link_telegram(db: OrmSession, user: User, init_data: str | None) -> None:
    """
    Привязывает Telegram к учётке по подписи из мини-приложения.

    Молча уходим при любой заминке: привязка — удобство (следующий запуск
    откроется без пароля), и ронять из-за неё вход или регистрацию нельзя.
    Чужой аккаунт не трогаем: если этот Telegram уже к кому-то привязан,
    оставляем как есть — разбираться, кто здесь настоящий, должен человек,
    а не молчаливая перезапись.
    """
    if not init_data:
        return
    config = settings()
    if not config.telegram_bot_token:
        return
    try:
        data = services.telegram.validate_init_data(init_data, config.telegram_bot_token)
    except Exception:
        log.info("привязка Telegram: подпись не сошлась")
        return

    profile = data.get("user") or {}
    telegram_id = profile.get("id")
    if not telegram_id:
        return
    username = services.telegram.clean_username(profile.get("username"))
    if user.telegram_id == telegram_id:
        # Уже привязан — но юзернейм человек мог сменить, и в админке
        # должен быть нынешний. Пустой не затирает: Telegram присылает его
        # не всегда, а потерять единственную зацепку хуже, чем показать
        # чуть устаревшую.
        if username and user.telegram_username != username:
            user.telegram_username = username
            db.commit()
        return

    if user.telegram_id:
        # К учётке уже привязан другой Telegram. Молча переписать его — значит
        # отдать вход без пароля тому, кто один раз узнал пароль. Перепривязка
        # — только через поддержку.
        log.info("привязка Telegram %s: у %s уже другой аккаунт, не трогаем", telegram_id, user.login)
        return
    taken = db.scalar(
        select(User).where(User.telegram_id == telegram_id, User.id != user.id).limit(1)
    )
    if taken is not None:
        log.info("привязка Telegram %s: уже за учёткой %s", telegram_id, taken.login)
        return

    user.telegram_id = telegram_id
    if username:
        user.telegram_username = username
    db.commit()
    log.info("Telegram %s привязан к %s", telegram_id, user.login)


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
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.retry_after), "X-Error-Code": "throttled"},
        ) from exc
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(exc), headers=_error_code_header(exc)
        ) from exc

    session = services.session_for_token(db, token)
    assert session is not None
    _link_telegram(db, user, body.init_data)
    _provision_for_login(db, user, session)
    servers = _servers_out(db, user, session, background)
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
        subscription_url=_subscription_url(db, session),
    )


LOGIN_PROVISION_SECONDS = 8


def _provision_for_login(db: OrmSession, user: User, session: Session) -> None:
    if not user.has_access() or not session.is_device:
        return
    services.compat.CLIENT_AWG_LEVEL.set(services.compat.awg_level(session.platform, session.app_version))
    warnings = services.ensure_keys(
        db,
        user,
        devices={session.device_key},
        deadline=time.monotonic() + LOGIN_PROVISION_SECONDS,
    )
    for warning in warnings:
        log.warning("вход %s: %s", user.public_id, warning)

    db.expire(user, ["keys"])


class RegisterRequest(BaseModel):

    # Регистрация из мини-приложения присылает подпись Telegram: по ней
    # учётка сразу привязывается к аккаунту, и в следующий раз человек
    # заходит без логина и пароля.
    init_data: str | None = Field(default=None, max_length=8192)
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=254)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=96)
    ref: str | None = Field(default=None, max_length=16)


class TgLoginRequest(BaseModel):

    init_data: str = Field(min_length=24, max_length=8192)
    app_version: str | None = Field(default=None, max_length=32)


@router.post("/login/telegram", response_model=LoginResponse)
def login_telegram(
    body: TgLoginRequest,
    request: Request,
    background: BackgroundTasks,
    db: OrmSession = Depends(get_db),
) -> LoginResponse:
    """
    Вход из мини-приложения Telegram: личность удостоверяет подпись initData.

    Пароль не спрашиваем — Telegram уже проверил, кто это. Учётку ищем по
    telegram_id, который привязал бот; не нашли — мини-приложение покажет
    обычную форму входа. Сессия платформы «telegram» слот устройства не
    занимает и ключей не выдаёт.
    """
    config = settings()
    if not config.telegram_bot_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "вход через Telegram не настроен",
            headers={"X-Error-Code": "tg_disabled"},
        )

    verdict = services.ratelimit.hit(
        db,
        f"tg-login:{ip_tag(client_ip(request))}",
        limit=30,
        window_minutes=5,
        lock_minutes=5,
    )
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "слишком часто, попробуйте позже",
            headers={"Retry-After": str(verdict.retry_after), "X-Error-Code": "throttled"},
        )

    try:
        data = services.telegram.validate_init_data(body.init_data, config.telegram_bot_token)
    except services.PanelError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(exc), headers=_error_code_header(exc)
        ) from exc

    profile = data.get("user") or {}
    telegram_id = profile.get("id")
    user = (
        db.scalar(
            select(User).where(User.telegram_id == telegram_id).order_by(User.id).limit(1)
        )
        if telegram_id
        else None
    )
    created = False
    if user is None and telegram_id:
        # Учётка могла остаться от покупки через бота: заказ помнит telegram_id,
        # даже если на самом пользователе привязки нет. Такую подхватываем, а не
        # плодим человеку второй аккаунт с чужой подпиской.
        user = _adopt_by_orders(db, telegram_id)
        if user is not None:
            user.telegram_id = telegram_id
            db.commit()
            log.info("Telegram %s подхватил учётку %s по заказу", telegram_id, user.login)

    if user is None and telegram_id:
        if not config.signup_enabled:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "регистрация сейчас закрыта",
                headers={"X-Error-Code": "signup_closed"},
            )
        # Подпись Telegram уже удостоверила личность — спрашивать логин с
        # паролем не за чем. Их выдаём сами: они понадобятся только тем, кто
        # захочет зайти с сайта, и лежат в профиле.
        tg_user = data.get("user") or {}
        display = (tg_user.get("first_name") or tg_user.get("username") or "").strip()[:128]
        # Логин берём из юзернейма: человек его помнит, а выданный
        # «имя-a3k9x2» — нет, и на компьютере ему потом этот логин вводить.
        # Юзернейма в Telegram может не быть — тогда прежний путь: транслит
        # имени со случайным хвостом.
        wanted = services.login_from_hint(db, services.telegram.clean_username(tg_user.get("username")))
        try:
            user, _password, _warnings = services.create_user(
                db,
                login=wanted,
                plan_code=config.signup_plan_code,
                name=display or None,
                note="регистрация из Telegram",
            )
        except services.PanelError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, str(exc), headers=_error_code_header(exc)
            ) from exc
        user.telegram_id = telegram_id
        db.commit()
        created = True
        log.info("Telegram %s: заведена учётка %s", telegram_id, user.login)

    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "не удалось определить пользователя Telegram",
            headers={"X-Error-Code": "tg_invalid"},
        )
    if user.is_blocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "доступ заблокирован", headers={"X-Error-Code": "blocked"}
        )
    if not user.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "доступ отключён", headers={"X-Error-Code": "disabled"}
        )

    # Вход из мини-приложения — самый свежий источник юзернейма: Telegram
    # прислал его прямо сейчас. Пустым не затираем, см. _link_telegram.
    username = services.telegram.clean_username(profile.get("username"))
    if username and user.telegram_username != username:
        user.telegram_username = username

    user.last_login_at = utcnow()
    token = services.open_session(
        db, user, platform="telegram", app_version=body.app_version
    )
    session = services.session_for_token(db, token)
    assert session is not None
    servers = _servers_out(db, user, session, background)
    log.info("вход из Telegram: %s (новая учётка: %s)", user.login, created)
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
        subscription_url=_subscription_url(db, session),
    )


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    request: Request,
    background: BackgroundTasks,
    db: OrmSession = Depends(get_db),
) -> LoginResponse:
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
        f"signup:{ip_tag(ip)}",
        limit=config.signup_max_per_ip,
        window_minutes=config.signup_window_minutes,
        lock_minutes=config.signup_window_minutes,
    )
    if not verdict.allowed:
        log.warning("регистрация заперта по частоте")
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

    # Пароль человек придумал сам — значит это уже его секрет, а не наша
    # выдача, и обратно мы его не показываем. Флаг ставит только
    # POST /account/credentials, а create_user — нет; без этой строки
    # GET /account/credentials отдавал бы придуманный пароль открытым
    # текстом наравне с выданным.
    user.credentials_set_at = utcnow()
    db.commit()

    if body.ref:
        try:
            services.referrals.register_from_site(db, body.ref, user)
        except Exception:
            db.rollback()
            log.exception("приглашение по коду %r не засчитано", body.ref)

    services.reset_login_throttle(db, body.login, ip)

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
    # Регистрация из мини-приложения: сразу привязываем Telegram, чтобы
    # следующий запуск открывался без логина и пароля.
    _link_telegram(db, user, body.init_data)
    _provision_for_login(db, user, session)
    servers = _servers_out(db, user, session, background)
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        account=AccountOut(public_id=user.public_id, login=user.login, name=user.name),
        subscription=_subscription_out(user),
        servers=servers,
        notice=_notice_for(db, user, servers),
        subscription_url=_subscription_url(db, session),
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
    services.touch(db, session, client_ip(request))
    user = session.user
    return {"ok": True, "active": user.has_access(), "subscription": _subscription_out(user).model_dump()}


class UpdateOut(BaseModel):

    update_available: bool
    version: str | None = None
    url: str | None = None
    changelog: str | None = None
    released_at: dt.datetime | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    mandatory: bool = False


@router.get("/version", response_model=UpdateOut)
def version(
    platform: str,
    current: str | None = None,
    db: OrmSession = Depends(get_db),
) -> UpdateOut:
    return UpdateOut(**services.check_update(db, platform, current))


@router.post("/logout")
def logout(
    session: Session = Depends(current_session), db: OrmSession = Depends(get_db)
) -> dict[str, bool]:
    session.revoked_at = services.utcnow()
    db.commit()
    return {"ok": True}


class RotateOut(BaseModel):
    subscription_url: str


@router.post("/subscription/rotate", response_model=RotateOut)
def subscription_rotate(
    session: Session = Depends(current_session),
    db: OrmSession = Depends(get_db),
) -> RotateOut:
    raw = services.subscription.rotate(
        db,
        session.user_id,
        session.device_key,
        label=session.device_name or session.platform,
    )
    return RotateOut(subscription_url=services.subscription.url_for(raw))
