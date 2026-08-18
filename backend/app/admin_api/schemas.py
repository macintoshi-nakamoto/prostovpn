"""
Формы ответов и запросов админского API.

Ключи в camelCase: их читает фронтенд, и переименовывать поля в каждом
компоненте руками — лишний повод для опечатки.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Schema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# --- вход --------------------------------------------------------------------


class LoginRequest(Schema):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(Schema):
    token: str
    expires_at: dt.datetime
    login: str


# --- тарифы ------------------------------------------------------------------


class PlanOut(Schema):
    id: int
    code: str
    name: str
    # Копейки — то, чем считает сайт и провайдер; рубли — то, что рисует
    # админка. Оба поля ставит Plan.set_price, врозь они не меняются.
    price: Decimal
    price_kopecks: int
    currency: str
    period_days: int
    traffic_limit_bytes: int | None
    server_limit: int
    device_limit: int
    allowed_regions: list[str] | None = None
    tagline: str | None = None
    is_active: bool
    is_public: bool


class PlanIn(Schema):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    price: Decimal = Decimal(0)
    period_days: int = Field(default=30, ge=1)
    traffic_limit_bytes: int | None = None
    server_limit: int = Field(default=3, ge=1)
    device_limit: int = Field(default=3, ge=1)
    # None — все страны. Иначе коды: ["NL", "DE", "FI"].
    allowed_regions: list[str] | None = None
    tagline: str | None = Field(default=None, max_length=160)
    is_active: bool = True
    # Показывать ли тариф на сайте. Выключенный остаётся доступным админу.
    is_public: bool = True


# --- пользователи ------------------------------------------------------------


class UserRow(Schema):
    """Строка списка: всё, что нужно видеть, не открывая карточку."""

    id: int
    public_id: str
    login: str
    name: str | None
    contact: str | None
    email: str | None = None
    telegram_id: int | None = None

    # online | offline | paused | blocked | expired | traffic
    status: str
    is_active: bool
    is_blocked: bool

    plan: str | None
    plan_name: str | None
    price: Decimal
    currency: str
    period_days: int | None
    subscription_started_at: dt.datetime | None
    expires_at: dt.datetime | None
    days_left: int | None

    traffic_used_bytes: int
    traffic_limit_bytes: int | None  # None — безлимит
    traffic_pct: float | None

    paid_total: Decimal
    last_payment_at: dt.datetime | None
    last_seen_at: dt.datetime | None
    last_login_at: dt.datetime | None = None
    # Подключён к VPN прямо сейчас — по свежему рукопожатию пира.
    is_online: bool
    # Открыто приложение — это другое событие: туннель может работать при
    # закрытом приложении, а приложение — быть открытым без туннеля.
    app_online: bool = False
    last_handshake_at: dt.datetime | None = None
    sessions_count: int
    # Занято устройств из скольких доступно по тарифу.
    devices_used: int = 0
    device_limit: int = 1
    servers_count: int
    # Человек сидит на iPhone и ходит по ключу AmneziaVPN, а не через наше
    # приложение. В списке это отдельная пометка: у таких клиентов другой
    # разговор в поддержке — им нечего переустанавливать и негде «войти».
    ios_access: bool = False
    # Ключ отключён администратором: пир снят, но ключ за учёткой остался и
    # включается обратно тем же — человеку ничего переставлять не придётся.
    ios_blocked: bool = False
    ios_keys_count: int = 0
    created_at: dt.datetime


class SessionOut(Schema):
    id: int
    platform: str | None
    app_version: str | None
    ip: str | None
    device_id: str | None = None
    device_name: str | None = None
    created_at: dt.datetime
    last_seen_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None
    is_online: bool
    # Занимает ли этот вход место в лимите тарифа. Кабинет в браузере — нет.
    is_device: bool = True
    # Поднят ли туннель через это устройство прямо сейчас.
    is_connected: bool = False


class PaymentOut(Schema):
    id: int
    amount: Decimal
    currency: str
    method: str | None
    comment: str | None
    paid_at: dt.datetime


class SubscriptionOut(Schema):
    id: int
    plan: str
    price: Decimal
    currency: str
    period_days: int
    auto_renew: bool
    starts_at: dt.datetime
    expires_at: dt.datetime
    is_cancelled: bool


class UserKeyOut(Schema):
    id: int
    server_id: int
    server_name: str
    # Устройство, которому принадлежит пир. Пустая строка — «ключ учётки»:
    # им ходят приложения, ещё не присылающие идентификатор установки.
    device_id: str = ""
    country: str | None
    country_code: str | None
    city: str | None
    provisioning: str
    address: str | None
    public_key: str | None
    rx_bytes: int
    tx_bytes: int
    last_handshake_at: dt.datetime | None
    created_at: dt.datetime
    revoked_at: dt.datetime | None


class IosKeyOut(Schema):
    """Готовая ссылка `vpn://` для одного устройства на одном сервере."""

    id: int
    slot: int
    name: str
    server_id: int
    server_name: str
    country: str | None = None
    country_code: str | None = None
    city: str | None = None
    address: str | None = None
    vpn_url: str
    traffic_bytes: int = 0
    last_handshake_at: dt.datetime | None = None
    created_at: dt.datetime
    is_active: bool = True


class OrderRow(Schema):
    """Строка раздела «Заказы» и истории покупок в карточке."""

    id: str
    plan_code: str
    plan_name: str | None = None
    email: str
    telegram_id: int | None = None
    amount_kopecks: int
    currency: str
    status: str  # pending | paid | failed | refunded | expired
    provider: str | None = None
    provider_payment_id: str | None = None
    is_renewal: bool
    failure_reason: str | None = None
    user_id: int | None = None
    user_login: str | None = None
    created_at: dt.datetime
    paid_at: dt.datetime | None = None
    # Дошло ли письмо. None — доставки по заказу не было.
    delivery_status: str | None = None


class UserDetail(UserRow):
    note: str | None
    # Пароль наружу не отдаётся вместе с карточкой: он приходит отдельным
    # запросом, и только этот запрос пишется в журнал. Здесь — лишь признак
    # того, что показывать вообще есть что.
    has_password: bool = False
    blocked_reason: str | None
    blocked_at: dt.datetime | None
    traffic_reset_at: dt.datetime | None
    sessions: list[SessionOut]
    payments: list[PaymentOut]
    subscriptions: list[SubscriptionOut]
    keys: list[UserKeyOut]
    orders: list[OrderRow] = []
    ios_keys: list[IosKeyOut] = []


class UserCreate(Schema):
    # Пусто — панель придумает сама. Так и задумано: пароли, набранные
    # руками, всегда слабее сгенерированных.
    login: str | None = None
    password: str | None = None
    name: str | None = None
    contact: str | None = None
    email: str | None = None
    note: str | None = None
    plan_code: str | None = "basic"
    days: int | None = None
    price: Decimal | None = None
    traffic_limit_bytes: int | None = None


class UserCreated(Schema):
    user: UserDetail
    # Единственный момент, когда пароль вообще отдаётся наружу.
    password: str
    warnings: list[str] = []


class UserUpdate(Schema):
    name: str | None = None
    contact: str | None = None
    email: str | None = None
    note: str | None = None


class TrafficLimitIn(Schema):
    # None — безлимит. Присылать гигабайты удобнее, чем байты руками.
    limit_gb: float | None = None
    unlimited: bool = False


class BlockIn(Schema):
    reason: str | None = None


class ExtendIn(Schema):
    days: int | None = Field(default=None, ge=1)
    plan_code: str | None = None
    price: Decimal | None = None
    # Отметить деньги как полученные: продление обычно и есть оплата.
    register_payment: bool = True
    method: str | None = None


class PasswordOut(Schema):
    password: str


class ActionResult(Schema):
    ok: bool = True
    warnings: list[str] = []
    message: str | None = None


# --- серверы -----------------------------------------------------------------


class ServerFacts(Schema):
    """
    Системные данные узла из последней проверки.

    Всё необязательное: узел мог быть недоступен, а показать то, что о нём
    известно, всё равно полезнее, чем прочерк во всю карточку.
    """

    os: str | None = None
    kernel: str | None = None
    arch: str | None = None
    hostname: str | None = None
    uptime_seconds: int | None = None
    load: str | None = None
    cpu_count: int | None = None
    cpu_model: str | None = None
    mem_total_bytes: int | None = None
    mem_available_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    disk_free_bytes: int | None = None
    awg_version: str | None = None
    awg_module_loaded: bool | None = None
    interface_up: bool | None = None
    interface_address: str | None = None
    interface_rx_bytes: int | None = None
    interface_tx_bytes: int | None = None
    peers: int | None = None
    listen_port: int | None = None
    public_ip: str | None = None
    ip_forward: bool | None = None
    panel_service: str | None = None
    awg_service: str | None = None


class ServerOut(Schema):
    id: int
    name: str
    country: str | None
    country_en: str | None
    city: str | None
    city_en: str | None
    country_code: str | None
    host: str
    port: int
    is_active: bool
    provisioning: str
    sort_order: int
    has_template: bool
    keys_total: int
    keys_active: int
    traffic_synced_at: dt.datetime | None
    traffic_error: str | None
    created_at: dt.datetime

    # Адрес и учётка SSH — не секрет: форма редактирования обязана показать
    # их такими, какие они есть, иначе она подставит свои значения по
    # умолчанию и сохранение уведёт панель на чужую машину. Пароль и ключ
    # SSH сюда не попадают никогда, шаблон и общий конфиг тоже: они
    # write-only и разослались бы в каждой строке списка.
    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_user: str | None = None
    has_ssh_secret: bool = False

    # Состояние по последней проверке. None — не проверяли ни разу.
    health_ok: bool | None = None
    health_summary: str | None = None
    health_checked_at: dt.datetime | None = None
    # Может ли узел выдать клиенту конфиг прямо сейчас — считается без
    # обращения к сети, по одним только настройкам.
    can_serve: bool = False
    facts: ServerFacts | None = None


class ServerIn(Schema):
    name: str = Field(min_length=1, max_length=128)
    country: str | None = None
    country_en: str | None = None
    city: str | None = None
    city_en: str | None = None
    country_code: str | None = None
    host: str = Field(min_length=1, max_length=255)
    port: int = 51820
    provisioning: str = "ssh"
    shared_config: str | None = None
    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_user: str | None = None
    ssh_password: str | None = None
    ssh_key: str | None = None
    awg_template: str | None = None
    is_active: bool = True
    sort_order: int = 0
    # Раздать ключи всем действующим пользователям сразу после добавления.
    issue_keys: bool = True


class ServerCreated(Schema):
    server: ServerOut
    issued: int
    warnings: list[str] = []


class CheckItem(Schema):
    name: str
    ok: bool
    detail: str = ""


class ServerCheck(Schema):
    """
    Отчёт проверки узла.

    `usable` — сможет ли клиент через него подключиться. Именно этот ответ
    нужен администратору, и именно его панель не давала: включённый сервер
    считался рабочим, а «включён» и «работает» — разные вещи.
    """

    server_id: int
    server_name: str
    usable: bool
    summary: str
    checks: list[CheckItem]


# --- ключи по серверам -------------------------------------------------------


class KeyRow(Schema):
    """Строка вкладки «Ключи»: кто, где и с каким ключом."""

    id: int
    user_id: int
    public_id: str
    login: str
    name: str | None
    user_status: str
    server_id: int
    server_name: str
    country: str | None
    country_code: str | None
    city: str | None
    provisioning: str
    device_id: str = ""
    address: str | None
    public_key: str | None
    rx_bytes: int
    tx_bytes: int
    last_handshake_at: dt.datetime | None
    created_at: dt.datetime
    revoked_at: dt.datetime | None
    is_active: bool


# --- деньги ------------------------------------------------------------------


class CalendarEntry(Schema):
    user_id: int | None = None
    public_id: str | None = None
    login: str | None = None
    name: str | None = None
    amount: Decimal
    method: str | None = None
    plan: str | None = None
    period_days: int | None = None
    at: dt.datetime | None = None


class CalendarDay(Schema):
    date: dt.date
    weekday: int
    is_today: bool
    is_past: bool
    actual: Decimal
    expected: Decimal
    payments: list[CalendarEntry]
    renewals: list[CalendarEntry]


class CalendarOut(Schema):
    year: int
    month: int
    days: list[CalendarDay]
    actual_total: Decimal
    expected_total: Decimal
    currency: str


class RevenueSummary(Schema):
    day: Decimal
    week: Decimal
    month: Decimal
    year: Decimal
    prev_day: Decimal
    prev_week: Decimal
    expected_month: Decimal
    currency: str


class PaymentIn(Schema):
    user_id: int | None = None
    amount: Decimal
    method: str | None = None
    comment: str | None = None
    paid_at: dt.datetime | None = None


class SeriesPoint(Schema):
    label: str
    value: Decimal


class Dashboard(Schema):
    users_total: int
    users_active: int
    users_blocked: int
    traffic_used_bytes: int
    servers_total: int
    servers_active: int
    # Сколько узлов реально способны выдать клиенту рабочий конфиг. Ноль при
    # ненулевом servers_active означает, что оплатившие люди прямо сейчас
    # не могут подключиться.
    servers_usable: int = 0
    # Открытые приложения. Отвечает на другой вопрос, чем users_online:
    # приложение может быть открыто с погашенным туннелем.
    sessions_online: int
    # Людей с поднятым туннелем прямо сейчас — это и есть «пользуются
    # сервисом». Без этого поля плитка на сводке молча показывала бы
    # количество открытых окон.
    users_online: int = 0
    revenue_day: Decimal
    revenue_month: Decimal
    revenue_year: Decimal
    currency: str
    daily: list[SeriesPoint]
    monthly: list[SeriesPoint]


# --- заказы, доставка, журнал ------------------------------------------------


class OrderStats(Schema):
    """Шапка раздела «Заказы»: где именно всё встало."""

    pending: int
    paid: int
    failed: int
    refunded: int
    expired: int
    # Оплачено, но письмо не ушло — это то, ради чего раздел и открывают.
    undelivered: int
    revenue_kopecks: int
    currency: str


class OrderList(Schema):
    items: list[OrderRow]
    stats: OrderStats


class DeliveryRow(Schema):
    id: int
    channel: str
    template: str
    target: str
    order_id: str | None = None
    user_id: int | None = None
    user_login: str | None = None
    attempts: int
    last_error: str | None = None
    next_attempt_at: dt.datetime
    sent_at: dt.datetime | None = None
    created_at: dt.datetime


class BillingEventRow(Schema):
    event_id: str
    provider: str
    kind: str | None = None
    order_id: str | None = None
    result: str | None = None
    received_at: dt.datetime


class AuditRow(Schema):
    id: int
    admin_id: int | None = None
    admin_login: str | None = None
    action: str
    target: str | None = None
    detail: str | None = None
    created_at: dt.datetime


class RevealOut(Schema):
    """Ответ на «показать пароль». Запрос обязательно попадает в журнал."""

    password: str


class OrderActionIn(Schema):
    reason: str | None = None


# --- файл раздельного туннелирования -----------------------------------------


class TunnelFileOut(Schema):
    id: int
    filename: str
    version: str | None = None
    size_bytes: int = 0
    sha256: str | None = None
    note: str | None = None
    is_active: bool = True
    updated_at: dt.datetime
    # Содержимое отдаём только по отдельному запросу: список доменов бывает
    # на сотни строк, и таскать его в каждой строке истории незачем.
    content: str | None = None


class TunnelFileIn(Schema):
    # Текстом, а не файлом: панель читает выбранный файл у себя и присылает
    # содержимое. Так же работает и правка списка прямо в панели, без
    # выгрузки-загрузки ради одной строки.
    content: str = Field(min_length=1)
    filename: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    note: str | None = None


# --- версии приложения -------------------------------------------------------


class ReleaseOut(Schema):
    id: int
    platform: str
    version: str
    url: str
    changelog: str | None
    size_bytes: int | None
    sha256: str | None
    is_mandatory: bool
    is_active: bool
    released_at: dt.datetime


class ReleaseIn(Schema):
    platform: str
    version: str = Field(min_length=1, max_length=32)
    url: str = Field(min_length=1)
    changelog: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    is_mandatory: bool = False
    is_active: bool = True
