from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Schema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class LoginRequest(Schema):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    # Код второго фактора — только у тех, кто его включил.
    code: str | None = Field(default=None, max_length=16)


class LoginResponse(Schema):
    token: str
    expires_at: dt.datetime
    login: str


class TotpStatus(Schema):
    enabled: bool
    enabled_at: dt.datetime | None = None
    pending: bool = False


class TotpSetupOut(Schema):
    secret: str
    otpauth_url: str


class TotpCodeIn(Schema):
    code: str = Field(min_length=6, max_length=16)


class PlanOut(Schema):
    id: int
    code: str
    name: str
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
    allowed_regions: list[str] | None = None
    tagline: str | None = Field(default=None, max_length=160)
    is_active: bool = True
    is_public: bool = True


class UserRow(Schema):

    id: int
    public_id: str
    login: str
    name: str | None
    contact: str | None
    email: str | None = None
    telegram_id: int | None = None
    telegram_username: str | None = None

    status: str
    is_active: bool
    is_blocked: bool
    is_free: bool = False

    plan: str | None
    plan_name: str | None
    price: Decimal
    currency: str
    period_days: int | None
    subscription_started_at: dt.datetime | None
    expires_at: dt.datetime | None
    days_left: int | None

    # Пауза подписки: дни стоят, доступа нет. `frozen_days` — сколько длится
    # текущая, `frozen_days_used` — сколько человек напаузил за всё время.
    is_frozen: bool = False
    frozen_at: dt.datetime | None = None
    frozen_days: int = 0
    frozen_days_used: int = 0
    freeze_count: int = 0

    traffic_used_bytes: int
    traffic_limit_bytes: int | None
    traffic_pct: float | None

    paid_total: Decimal
    last_payment_at: dt.datetime | None
    last_seen_at: dt.datetime | None
    last_login_at: dt.datetime | None = None
    is_online: bool
    app_online: bool = False
    last_handshake_at: dt.datetime | None = None
    sessions_count: int
    devices_used: int = 0
    device_limit: int = 1
    # С какого числа адресов сидели под одним ключом в последний обход и
    # сколько обходов подряд их больше нормы.
    shared_ips: int = 0
    shared_strikes: int = 0
    shared_ips_at: dt.datetime | None = None
    servers_count: int
    ios_access: bool = False
    ios_blocked: bool = False
    ios_keys_count: int = 0
    created_at: dt.datetime


class SessionOut(Schema):
    id: int
    platform: str | None
    app_version: str | None
    device_id: str | None = None
    created_at: dt.datetime
    last_seen_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None
    is_online: bool
    is_device: bool = True
    is_connected: bool = False


class PaymentOut(Schema):
    id: int
    amount: Decimal
    currency: str
    method: str | None
    comment: str | None
    external_id: str | None = None
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
    endpoint_port: int | None = None
    created_at: dt.datetime
    revoked_at: dt.datetime | None


class EndpointCredOut(Schema):
    """Учётка VLESS/Hysteria2 на узле: Happ, Hiddify, ссылка-подписка,
    запасной ключ AmneziaVPN. Трафик и «последний раз видели» — из
    счётчиков xray/hy2, которые панель снимает раз в минуту."""

    id: int
    server_id: int
    server_name: str
    country: str | None = None
    country_code: str | None = None
    city: str | None = None
    endpoint_handle: str | None = None
    endpoint_port: int | None = None
    cred_type: str = "vless"
    device_id: str = ""
    label: str | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0
    last_seen_at: dt.datetime | None = None
    is_connected: bool = False
    created_at: dt.datetime


class IosKeyOut(Schema):

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
    is_connected: bool = False
    disconnected: bool = False


class OrderRow(Schema):

    id: str
    plan_code: str
    plan_name: str | None = None
    email: str
    telegram_id: int | None = None
    amount_kopecks: int
    currency: str
    status: str
    provider: str | None = None
    payment_method: str | None = None
    provider_payment_id: str | None = None
    is_renewal: bool
    failure_reason: str | None = None
    user_id: int | None = None
    user_login: str | None = None
    created_at: dt.datetime
    paid_at: dt.datetime | None = None
    delivery_status: str | None = None


class UserDetail(UserRow):
    note: str | None
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
    ios_max_keys: int = 0
    ios_can_add: bool = False
    creds: list[EndpointCredOut] = []


class UserCreate(Schema):
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
    password: str
    warnings: list[str] = []


class UserUpdate(Schema):
    name: str | None = None
    contact: str | None = None
    email: str | None = None
    note: str | None = None
    is_free: bool | None = None


class TrafficLimitIn(Schema):
    limit_gb: float | None = None
    unlimited: bool = False


class BlockIn(Schema):
    reason: str | None = None


class ExtendIn(Schema):
    days: int | None = Field(default=None, ge=1)
    plan_code: str | None = None
    price: Decimal | None = None
    register_payment: bool = True
    method: str | None = None
    external_id: str | None = None
    order_provider: str | None = None
    payment_method: str | None = None
    quantity: int = Field(default=1, ge=1)


class PasswordOut(Schema):
    password: str


class ActionResult(Schema):
    ok: bool = True
    warnings: list[str] = []
    message: str | None = None


class ServerFacts(Schema):

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


class AgentOut(Schema):
    """Сводка по последнему снимку агента на узле (services/agent.py)."""

    version: str | None = None
    seen_at: dt.datetime | None = None
    stale: bool = True
    awg_ok: bool = False
    xray_ok: bool = False
    hy2_ok: bool = False
    peers: int = 0
    online_vless: int = 0
    online_hy2: int = 0
    load1: float = 0.0
    mem_avail_mb: int = 0
    uptime_s: int = 0
    took_ms: int = 0
    trouble: str | None = None
    trouble_since: dt.datetime | None = None


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
    alt_ports: str = ""
    is_active: bool
    provisioning: str
    sort_order: int
    has_template: bool
    keys_total: int
    keys_active: int
    traffic_synced_at: dt.datetime | None
    traffic_error: str | None
    last_ok_at: dt.datetime | None = None
    down_since: dt.datetime | None = None
    alert_sent_at: dt.datetime | None = None
    created_at: dt.datetime

    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_user: str | None = None
    has_ssh_secret: bool = False

    health_ok: bool | None = None
    health_summary: str | None = None
    health_checked_at: dt.datetime | None = None
    can_serve: bool = False
    facts: ServerFacts | None = None
    agent: AgentOut | None = None


class ServerIn(Schema):
    name: str = Field(min_length=1, max_length=128)
    country: str | None = None
    country_en: str | None = None
    city: str | None = None
    city_en: str | None = None
    country_code: str | None = None
    host: str = Field(min_length=1, max_length=255)
    port: int = 51820
    alt_ports: str = ""
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

    server_id: int
    server_name: str
    usable: bool
    summary: str
    checks: list[CheckItem]


class KeyRow(Schema):

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
    endpoint_port: int | None = None
    created_at: dt.datetime
    revoked_at: dt.datetime | None
    is_active: bool


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
    servers_usable: int = 0
    sessions_online: int
    users_online: int = 0
    revenue_day: Decimal
    revenue_month: Decimal
    revenue_year: Decimal
    currency: str
    daily: list[SeriesPoint]
    monthly: list[SeriesPoint]


class FunnelStage(Schema):
    key: str
    label: str
    count: int
    pct_total: float
    pct_prev: float


class FunnelSource(Schema):
    source: str
    label: str
    registered: int
    setup: int
    connected: int
    paid: int


class FunnelCohort(Schema):
    week: str
    label: str
    registered: int
    setup: int
    connected: int
    paid: int


class FunnelStuckUser(Schema):
    id: int
    public_id: str
    login: str
    name: str | None = None
    telegram_username: str | None = None
    created_at: dt.datetime
    source: str
    has_setup: bool
    access_active: bool


class FunnelOut(Schema):
    """Воронка регистрация → доступ → подключение → оплата; см. services/funnel.py."""

    period_days: int | None = None
    users: int
    stages: list[FunnelStage]
    sources: list[FunnelSource]
    cohorts: list[FunnelCohort]
    stuck_count: int
    stuck: list[FunnelStuckUser]
    cooled_count: int
    median_hours_to_connect: float | None = None
    median_days_to_pay: float | None = None
    generated_at: dt.datetime


class TelemetryCell(Schema):
    attempts: int
    ok: int
    ok_pct: float
    median_ms: int | None = None


class TelemetryProtocol(TelemetryCell):
    protocol: str


class TelemetryOperator(TelemetryCell):
    operator: str
    protocol: str


class TelemetryKind(TelemetryCell):
    kind: str
    protocol: str


class TelemetryServer(TelemetryCell):
    server_id: int | None = None
    server: str
    protocol: str


class TelemetryPlatform(TelemetryCell):
    platform: str
    app_version: str


class TelemetryError(Schema):
    error: str
    count: int


class TelemetryFailure(Schema):
    at: dt.datetime
    platform: str
    app_version: str | None = None
    network_kind: str
    operator: str | None = None
    protocol: str
    server: str
    port: int | None = None
    stage: str
    duration_ms: int
    attempts: int
    error: str | None = None


class TelemetryOut(Schema):
    """Сводка телеметрии подключений; см. services/telemetry.py."""

    period_days: int
    reports: int
    ok: int
    ok_pct: float
    users_reporting: int
    users_never_ok: int
    protocols: list[TelemetryProtocol]
    operators: list[TelemetryOperator]
    kinds: list[TelemetryKind]
    servers: list[TelemetryServer]
    platforms: list[TelemetryPlatform]
    errors: list[TelemetryError]
    recent_failures: list[TelemetryFailure]
    generated_at: dt.datetime


class TelemetryChange(Schema):
    operator: str | None = None
    protocol: str
    attempts: int
    ok_pct: float
    prev_attempts: int
    prev_ok_pct: float | None = None
    delta: float | None = None


class TelemetryChangesOut(Schema):
    """Сегодня против вчера по операторам и протоколам; см. telemetry.changes."""

    hours: int
    reports: int
    ok_pct: float
    prev_reports: int
    prev_ok_pct: float | None = None
    items: list[TelemetryChange]
    protocols: list[TelemetryChange]
    errors: list[TelemetryError]
    generated_at: dt.datetime


class OrderStats(Schema):

    pending: int
    paid: int
    failed: int
    refunded: int
    expired: int
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

    password: str


class OrderActionIn(Schema):
    reason: str | None = None


class TunnelFileOut(Schema):
    id: int
    filename: str
    version: str | None = None
    size_bytes: int = 0
    sha256: str | None = None
    note: str | None = None
    is_active: bool = True
    updated_at: dt.datetime
    content: str | None = None


class TunnelFileIn(Schema):
    content: str = Field(min_length=1)
    filename: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    note: str | None = None


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
