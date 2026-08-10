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
    price: Decimal
    currency: str
    period_days: int
    traffic_limit_bytes: int | None
    is_active: bool


class PlanIn(Schema):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    price: Decimal = Decimal(0)
    period_days: int = Field(default=30, ge=1)
    traffic_limit_bytes: int | None = None
    is_active: bool = True


# --- пользователи ------------------------------------------------------------


class UserRow(Schema):
    """Строка списка: всё, что нужно видеть, не открывая карточку."""

    id: int
    public_id: str
    login: str
    name: str | None
    contact: str | None

    status: str  # active | paused | blocked | expired | traffic
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
    is_online: bool
    sessions_count: int
    servers_count: int
    created_at: dt.datetime


class SessionOut(Schema):
    id: int
    platform: str | None
    app_version: str | None
    ip: str | None
    created_at: dt.datetime
    last_seen_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None
    is_online: bool


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


class UserDetail(UserRow):
    note: str | None
    password_hint: str | None
    blocked_reason: str | None
    blocked_at: dt.datetime | None
    traffic_reset_at: dt.datetime | None
    sessions: list[SessionOut]
    payments: list[PaymentOut]
    subscriptions: list[SubscriptionOut]
    keys: list[UserKeyOut]


class UserCreate(Schema):
    # Пусто — панель придумает сама. Так и задумано: пароли, набранные
    # руками, всегда слабее сгенерированных.
    login: str | None = None
    password: str | None = None
    name: str | None = None
    contact: str | None = None
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


class ServerOut(Schema):
    id: int
    name: str
    country: str | None
    country_en: str | None
    city: str | None
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


class ServerIn(Schema):
    name: str = Field(min_length=1, max_length=128)
    country: str | None = None
    country_en: str | None = None
    city: str | None = None
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
    sessions_online: int
    revenue_day: Decimal
    revenue_month: Decimal
    revenue_year: Decimal
    currency: str
    daily: list[SeriesPoint]
    monthly: list[SeriesPoint]


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
