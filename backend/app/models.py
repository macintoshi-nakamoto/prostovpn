from __future__ import annotations

import datetime as dt
import math
import enum
import secrets
import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sa_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_public_id() -> str:
    block = lambda: "".join(secrets.choice(_ID_ALPHABET) for _ in range(4))
    return f"PV-{block()}-{block()}"


def new_referral_code() -> str:
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))


def new_uuid() -> str:
    return str(uuid.uuid4())


GB = 1024 ** 3

HANDSHAKE_WINDOW = dt.timedelta(minutes=3)

WEB_PLATFORMS = frozenset({"web", "site", "browser"})

# Бот ходит в панель тем же /login, что и приложения (bot/utils/panel.py),
# но телеграм — не устройство: в кабинете он не показывается и в лимит
# тарифа не идёт.
BOT_PLATFORMS = frozenset({"telegram", "bot"})

NON_DEVICE_PLATFORMS = WEB_PLATFORMS | BOT_PLATFORMS

IOS_SLOT_PREFIX = "ios-"

IOS_MAX_KEYS = 5


def is_ios_slot(device_id: str | None) -> bool:
    return (device_id or "").startswith(IOS_SLOT_PREFIX)


def ios_slot_number(device_id: str | None) -> int:
    if not is_ios_slot(device_id):
        return 0
    tail = (device_id or "")[len(IOS_SLOT_PREFIX) :]
    return int(tail) if tail.isdigit() else 0


def ios_slot(number: int) -> str:
    return f"{IOS_SLOT_PREFIX}{number}"


def sanitize_device_id(device_id: str | None) -> str | None:
    value = (device_id or "").strip()
    if not value:
        return device_id
    while is_ios_slot(value):
        value = value[len(IOS_SLOT_PREFIX) :]
    return value or None


def is_device_platform(platform: str | None) -> bool:
    return (platform or "").strip().lower() not in NON_DEVICE_PLATFORMS


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


class Admin(Base):

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class AdminSession(Base):

    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    admin: Mapped[Admin] = relationship()


class Provisioning(str, enum.Enum):

    SHARED = "shared"
    SSH = "ssh"


class Plan(Base):

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    price_kopecks: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)

    server_limit: Mapped[int] = mapped_column(Integer, default=3)
    device_limit: Mapped[int] = mapped_column(Integer, default=3)
    allowed_regions: Mapped[list[str] | None] = mapped_column(JSON, default=None)

    tagline: Mapped[str | None] = mapped_column(String(160), default=None)
    # Цена первой покупки в копейках. 0 — вводной цены нет. Действует один раз
    # на человека: следующие списания идут по price_kopecks, поэтому
    # автопродление трогать не пришлось.
    intro_price_kopecks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    def set_price(self, kopecks: int) -> None:
        self.price_kopecks = int(kopecks)
        self.price = Decimal(kopecks) / 100


class Server(Base):

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(64), default=None)
    country_en: Mapped[str | None] = mapped_column(String(64), default=None)
    city: Mapped[str | None] = mapped_column(String(64), default=None)
    city_en: Mapped[str | None] = mapped_column(String(64), default=None)
    country_code: Mapped[str | None] = mapped_column(String(8), default=None)

    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=51820)
    alt_ports: Mapped[str] = mapped_column(String(120), default="", server_default="")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    provisioning: Mapped[Provisioning] = mapped_column(
        Enum(Provisioning, native_enum=False), default=Provisioning.SHARED
    )
    shared_config: Mapped[str | None] = mapped_column(Text, default=None)

    ssh_host: Mapped[str | None] = mapped_column(String(255), default=None)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str | None] = mapped_column(String(64), default=None)
    ssh_password: Mapped[str | None] = mapped_column(Text, default=None)
    ssh_key: Mapped[str | None] = mapped_column(Text, default=None)
    awg_template: Mapped[str | None] = mapped_column(Text, default=None)

    def alt_port_list(self) -> list[int]:
        out: list[int] = []
        for chunk in (self.alt_ports or "").replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk.isdigit():
                continue
            value = int(chunk)
            if 0 < value < 65536 and value != self.port and value not in out:
                out.append(value)
        return out

    traffic_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    traffic_error: Mapped[str | None] = mapped_column(Text, default=None)

    health_ok: Mapped[bool | None] = mapped_column(Boolean, default=None)
    health_summary: Mapped[str | None] = mapped_column(Text, default=None)
    health_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    facts: Mapped[dict | None] = mapped_column(JSON, default=None)

    endpoints_seeded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )

    endpoint_rev: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    keys: Mapped[list["UserKey"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    endpoints: Mapped[list["NodeEndpoint"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )

    def live_endpoints(self, kind: "EndpointKind | None" = None) -> list["NodeEndpoint"]:
        return [
            ep
            for ep in self.endpoints
            if ep.is_live and (kind is None or ep.kind == kind)
        ]


class EndpointKind(str, enum.Enum):

    AWG = "awg"
    VLESS = "vless"


class EndpointState(str, enum.Enum):

    DRAFT = "draft"
    ACTIVE = "active"
    DRAINING = "draining"
    RETIRED = "retired"


class NodeEndpoint(Base):

    __tablename__ = "node_endpoints"
    __table_args__ = (
        Index("uq_endpoint_server_handle", "server_id", "handle", unique=True),
        Index("uq_endpoint_server_port", "server_id", "listen_port", unique=True),
        Index("uq_endpoint_server_subnet", "server_id", "subnet", unique=True),
        Index("ix_endpoint_server_state", "server_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)

    kind: Mapped[EndpointKind] = mapped_column(
        Enum(EndpointKind, native_enum=False), default=EndpointKind.AWG
    )
    transport: Mapped[str] = mapped_column(String(8), default="udp", server_default="udp")

    handle: Mapped[str] = mapped_column(String(32))
    listen_port: Mapped[int] = mapped_column(Integer)
    alt_ports: Mapped[str] = mapped_column(String(120), default="", server_default="")
    host_override: Mapped[str | None] = mapped_column(String(255), default=None)
    subnet: Mapped[str | None] = mapped_column(String(32), default=None)

    params: Mapped[dict | None] = mapped_column(JSON, default=None)
    secret_enc: Mapped[str | None] = mapped_column(Text, default=None)

    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    capacity: Mapped[int | None] = mapped_column(Integer, default=None)
    state: Mapped[EndpointState] = mapped_column(
        Enum(EndpointState, native_enum=False), default=EndpointState.DRAFT
    )
    counter_mode: Mapped[str] = mapped_column(
        String(16), default="absolute", server_default="absolute"
    )
    rev: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    server: Mapped["Server"] = relationship(back_populates="endpoints")

    @property
    def is_live(self) -> bool:
        return self.state in (EndpointState.ACTIVE, EndpointState.DRAINING)

    @property
    def accepts_new(self) -> bool:
        return self.state == EndpointState.ACTIVE

    def public_host(self, server: "Server | None" = None) -> str:
        return self.host_override or (server or self.server).host

    def alt_port_list(self) -> list[int]:
        out: list[int] = []
        for chunk in (self.alt_ports or "").replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk.isdigit():
                continue
            value = int(chunk)
            if 0 < value < 65536 and value != self.listen_port and value not in out:
                out.append(value)
        return out

    def obfuscation(self):
        if self.kind != EndpointKind.AWG or not self.params:
            return None
        from .obfuscation import InvalidObfuscation, validate

        try:
            return validate(self.params, strict=False)
        except InvalidObfuscation:
            return None


class UserEndpointCred(Base):

    __tablename__ = "user_endpoint_creds"
    __table_args__ = (
        Index("uq_uec_slot", "endpoint_id", "user_id", "device_id", unique=True),
        Index("uq_uec_label", "endpoint_id", "label", unique=True),
        Index("uq_uec_fp", "endpoint_id", "identity_fp", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    endpoint_id: Mapped[int] = mapped_column(
        ForeignKey("node_endpoints.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[str] = mapped_column(String(64), default="", server_default="", index=True)

    cred_type: Mapped[str] = mapped_column(String(32), default="vless", server_default="vless")
    identity_enc: Mapped[str | None] = mapped_column(Text, default=None)
    identity_fp: Mapped[str | None] = mapped_column(String(64), default=None)
    label: Mapped[str | None] = mapped_column(String(64), default=None)
    extra: Mapped[dict | None] = mapped_column(JSON, default=None)

    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    traffic_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    disconnected_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped["User"] = relationship()
    endpoint: Mapped["NodeEndpoint"] = relationship()

    @property
    def identity(self) -> str | None:
        if not self.identity_enc:
            return None
        from . import crypto

        try:
            return crypto.decrypt(self.identity_enc)
        except crypto.SecretsUnavailable:
            return None


class User(Base):

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, index=True, default=new_public_id)
    referral_code: Mapped[str | None] = mapped_column(
        String(16), unique=True, index=True, default=None
    )
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    password_enc: Mapped[str | None] = mapped_column(Text, default=None)
    password_hint: Mapped[str | None] = mapped_column(String(128), default=None)
    name: Mapped[str | None] = mapped_column(String(128), default=None)
    contact: Mapped[str | None] = mapped_column(String(128), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, default=None)
    email_enc: Mapped[str | None] = mapped_column(Text, default=None)
    email_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, default=None)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True, default=None)
    # @юзернейм из Telegram — только для показа в админке: по нему человека
    # находят глазами, тогда как telegram_id ни о чём не говорит. Хранится
    # без «@» и может быть пустым: юзернейм в Telegram не обязателен, и его
    # меняют — на связку учётки с Telegram опираться нельзя, для этого есть id.
    telegram_username: Mapped[str | None] = mapped_column(String(32), default=None)

    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    # Когда человек сам задал логин/пароль. Пусто — данные выданы автоматически
    # (регистрация из Telegram или покупка через бота), и их можно показать
    # владельцу в профиле: он их ни разу не видел.
    credentials_set_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, default=None)
    blocked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    is_free: Mapped[bool] = mapped_column(Boolean, default=False)

    # Заморозка подписки. Пока стоит дата, часы подписки не идут: дни не
    # тратятся, но и доступа нет. Даты в самих подписках при этом не
    # трогаются — их сдвигает разморозка, см. services/freeze.py.
    frozen_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    frozen_days_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    freeze_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Месячный лимит пауз: месяц «ГГГГ-ММ» и сколько раз в нём морозили.
    # Смена месяца обнуляет счёт — см. services/freeze.py.
    freeze_month: Mapped[str | None] = mapped_column(String(7), default=None)
    freeze_month_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    traffic_unlimited: Mapped[bool] = mapped_column(Boolean, default=False)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_reset_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    ios_access: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    ios_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    keys: Mapped[list["UserKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def is_frozen(self) -> bool:
        return self.frozen_at is not None

    def frozen_for(self, now: dt.datetime | None = None) -> dt.timedelta:
        """Сколько длится текущая заморозка. Не заморожен — ноль."""
        if self.frozen_at is None:
            return dt.timedelta(0)

        return max(dt.timedelta(0), (now or utcnow()) - self.frozen_at)

    def subscription_clock(self, now: dt.datetime | None = None) -> dt.datetime:
        """
        Часы подписки: во время заморозки они стоят на минуте заморозки.

        Дни считаются от этого момента, поэтому у замороженной подписки
        остаток не тает, а даты в базе можно не трогать до разморозки —
        сдвинуть их одним разом дешевле и честнее, чем пересчитывать каждую
        подписку в очереди при каждой паузе.

        Повторное применение безвредно: часы уже стоящей подписки возвращают
        сами себя. Это важно, потому что методы ниже передают полученный
        момент дальше по цепочке.
        """
        moment = now or utcnow()

        if self.frozen_at is not None and self.frozen_at < moment:
            return self.frozen_at

        return moment

    def active_subscription(self, now: dt.datetime | None = None) -> "Subscription | None":
        moment = self.subscription_clock(now)
        running = [
            s
            for s in self.subscriptions
            if not s.is_cancelled and s.starts_at <= moment < s.expires_at
        ]
        return max(running, key=lambda s: s.expires_at, default=None)

    def upcoming_subscriptions(self, now: dt.datetime | None = None) -> list["Subscription"]:
        moment = self.subscription_clock(now)
        return sorted(
            (
                s
                for s in self.subscriptions
                if not s.is_cancelled and s.starts_at > moment and s.expires_at > moment
            ),
            key=lambda s: s.starts_at,
        )

    def access_expires_at(self, now: dt.datetime | None = None) -> dt.datetime | None:
        moment = self.subscription_clock(now)
        ends = [
            s.expires_at
            for s in self.subscriptions
            if not s.is_cancelled and s.expires_at > moment
        ]
        return max(ends, default=None)

    def access_days_left(self, now: dt.datetime | None = None) -> int | None:
        """Целых суток доступа впереди — округление вниз.

        Это «сколько можно отдать»: передача дней и проверки лимитов
        считают только полные сутки. Для показа человеку есть
        access_days_left_display.
        """
        moment = self.subscription_clock(now)
        end = self.access_expires_at(moment)
        return max(0, (end - moment).days) if end is not None else None

    def access_days_left_display(self, now: dt.datetime | None = None) -> int | None:
        """Дней доступа для витрин — округление вверх.

        Округление вниз врёт почти всю жизнь подписки: купил два дня,
        через час осталось 1.96 — и человек читает «остался 1 день»,
        хотя сервис работает ещё почти двое суток. Показываем то, что
        человек считает днями: пока идут последние сутки — «1 день».
        """
        moment = self.subscription_clock(now)
        end = self.access_expires_at(moment)
        if end is None:
            return None
        seconds = (end - moment).total_seconds()
        if seconds <= 0:
            return 0
        return int(math.ceil(seconds / 86400))

    def access_ends_if_resumed(self, now: dt.datetime | None = None) -> dt.datetime | None:
        """
        До какого числа хватит доступа, если разморозить прямо сейчас.

        Витринам нужна именно эта дата: в базе у замороженного лежит старая,
        она уже «прошла» и показывать её человеку нельзя. У обычного
        пользователя ничего не меняется — заморозки нет, сдвиг нулевой.
        """
        end = self.access_expires_at(now)

        return end + self.frozen_for(now) if end is not None else None

    def effective_traffic_limit(self, now: dt.datetime | None = None) -> int | None:
        if self.traffic_unlimited:
            return None
        if self.traffic_limit_bytes is not None:
            return self.traffic_limit_bytes
        sub = self.active_subscription(now)
        if sub is not None and sub.plan_ref is not None:
            return sub.plan_ref.traffic_limit_bytes
        return None

    def current_plan(self, now: dt.datetime | None = None) -> "Plan | None":
        sub = self.active_subscription(now)
        return sub.plan_ref if sub is not None else None

    def device_limit(self, now: dt.datetime | None = None) -> int:
        plan = self.current_plan(now)
        return plan.device_limit if plan is not None else 1

    def ios_slot_numbers(self) -> list[int]:
        numbers = {ios_slot_number(key.device_id) for key in self.keys}
        return sorted(n for n in numbers if n > 0)

    def ios_slots(self, now: dt.datetime | None = None) -> list[str]:
        if not self.ios_access or self.ios_blocked:
            return []
        rows: dict[int, list["UserKey"]] = {}
        for key in self.keys:
            number = ios_slot_number(key.device_id)
            if number > 0:
                rows.setdefault(number, []).append(key)
        if not rows:
            return [ios_slot(1)]
        numbers = sorted(
            number
            for number, keys in rows.items()
            if not all(key.disconnected_at is not None for key in keys)
        )[:IOS_MAX_KEYS]
        return [ios_slot(n) for n in numbers]

    def server_limit(self, now: dt.datetime | None = None) -> int | None:
        plan = self.current_plan(now)
        return plan.server_limit if plan is not None else None

    def allowed_regions(self, now: dt.datetime | None = None) -> list[str] | None:
        plan = self.current_plan(now)
        return plan.allowed_regions if plan is not None else None

    def live_sessions(self, now: dt.datetime | None = None) -> list["Session"]:
        moment = now or utcnow()
        return [s for s in self.sessions if s.revoked_at is None and s.expires_at > moment]

    def device_sessions(self, now: dt.datetime | None = None) -> list["Session"]:
        return [s for s in self.live_sessions(now) if s.is_device]

    def devices(self, now: dt.datetime | None = None) -> dict[str, "Session"]:
        found: dict[str, Session] = {}
        for session in self.device_sessions(now):
            current = found.get(session.device_key)
            if current is None or session.last_seen_at > current.last_seen_at:
                found[session.device_key] = session
        return found

    def is_locked_out(self, now: dt.datetime | None = None) -> bool:
        return self.locked_until is not None and self.locked_until > (now or utcnow())

    def set_email(self, address: str | None) -> None:
        from . import crypto

        if address is None:
            self.email = None
            self.email_enc = None
            self.email_hash = None
            return

        normalized = normalize_email(address)
        self.email_hash = crypto.blind_index(normalized)
        encrypted = crypto.encrypt_or_none(normalized)
        self.email_enc = encrypted
        self.email = None if encrypted else normalized

    @property
    def email_plain(self) -> str | None:
        if self.email_enc:
            from . import crypto

            try:
                return crypto.decrypt(self.email_enc)
            except crypto.SecretsUnavailable:
                return None
        return self.email

    def last_handshake(self) -> dt.datetime | None:
        stamps = [
            key.last_handshake_at
            for key in self.keys
            if key.revoked_at is None and key.last_handshake_at is not None
        ]
        return max(stamps, default=None)

    def is_vpn_connected(self, now: dt.datetime | None = None) -> bool:
        stamp = self.last_handshake()
        if stamp is None:
            return False
        return stamp > (now or utcnow()) - HANDSHAKE_WINDOW

    def traffic_exhausted(self, now: dt.datetime | None = None) -> bool:
        limit = self.effective_traffic_limit(now)
        return limit is not None and self.traffic_used_bytes >= limit

    def has_access(self, now: dt.datetime | None = None) -> bool:
        if self.is_blocked or not self.is_active:
            return False
        # Заморозка — это пауза и для доступа тоже. Иначе она была бы просто
        # бесплатной прибавкой к сроку: дни стоят, а VPN работает.
        if self.is_frozen:
            return False
        if self.active_subscription(now) is None:
            return False
        return not self.traffic_exhausted(now)


class UserKey(Base):

    __tablename__ = "user_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "server_id", "device_id", name="uq_user_server_device_key"),
        Index("uq_user_keys_server_address", "server_id", "address", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    endpoint_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    device_id: Mapped[str] = mapped_column(
        String(64), default="", server_default="", index=True
    )

    config: Mapped[str] = mapped_column(Text)
    private_key_enc: Mapped[str | None] = mapped_column(Text, default=None)
    public_key: Mapped[str | None] = mapped_column(String(64), default=None)
    address: Mapped[str | None] = mapped_column(String(64), default=None)

    endpoint_port: Mapped[int | None] = mapped_column(Integer, default=None)
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_handshake_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    traffic_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    disconnected_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship(back_populates="keys")
    server: Mapped[Server] = relationship(back_populates="keys")


class TrafficSample(Base):

    __tablename__ = "traffic_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    delta_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sampled_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Subscription(Base):

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(64), default="basic")
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL"), index=True, default=None
    )
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)

    is_bonus: Mapped[bool] = mapped_column(Boolean, default=False)

    starts_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="subscriptions")
    plan_ref: Mapped[Plan | None] = relationship()


class Payment(Base):

    __tablename__ = "payments"
    __table_args__ = (
        Index(
            "uq_payment_order_positive",
            "order_id",
            unique=True,
            sqlite_where=sa_text("order_id IS NOT NULL AND amount > 0"),
            postgresql_where=sa_text("order_id IS NOT NULL AND amount > 0"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True, default=None
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, default=None
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    method: Mapped[str | None] = mapped_column(String(64), default=None)
    external_id: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    paid_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)

    user: Mapped[User | None] = relationship(back_populates="payments")


class Session(Base):

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform: Mapped[str | None] = mapped_column(String(32), default=None)
    app_version: Mapped[str | None] = mapped_column(String(32), default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    device_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    device_name: Mapped[str | None] = mapped_column(String(96), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship(back_populates="sessions")

    @property
    def is_device(self) -> bool:
        return is_device_platform(self.platform)

    @property
    def device_key(self) -> str:
        return (self.device_id or "").strip()


class SubscriptionToken(Base):

    __tablename__ = "subscription_tokens"
    __table_args__ = (
        Index(
            "uq_sub_token_user_device",
            "user_id",
            "device_id",
            unique=True,
            sqlite_where=sa_text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(64), default="", server_default="", index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Сам токен, зашифрованный AES-GCM. Хэша хватало, пока ссылку показывали
    # один раз при выпуске; теперь она живёт на экране установки постоянно,
    # а восстановить её из хэша нельзя. Хранение то же, что у пароля
    # (password_enc): без PANEL_SECRETS_KEY поле остаётся пустым, и тогда
    # ссылка просто не показывается — выпустить новую человек всегда может.
    token_enc: Mapped[str | None] = mapped_column(Text, default=None)
    label: Mapped[str | None] = mapped_column(String(96), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship()


class PasswordReset(Base):

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    requested_ip: Mapped[str | None] = mapped_column(String(64), default=None)

    user: Mapped[User] = relationship()

    def is_usable(self, now: dt.datetime | None = None) -> bool:
        moment = now or utcnow()
        return self.used_at is None and self.expires_at > moment


class AppRelease(Base):

    __tablename__ = "app_releases"
    __table_args__ = (UniqueConstraint("platform", "version", name="uq_release_platform_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text)
    changelog: Mapped[str | None] = mapped_column(Text, default=None)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    released_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class OrderStatus(str, enum.Enum):

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class Order(Base):

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_order_provider_payment"),
        CheckConstraint(
            "status in ('pending','paid','failed','refunded','expired')", name="ck_order_status"
        ),
        Index("ix_orders_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code", ondelete="RESTRICT"), index=True)

    email: Mapped[str] = mapped_column(String(255), index=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    platform: Mapped[str | None] = mapped_column(String(16), default=None)

    quantity: Mapped[int] = mapped_column(Integer, default=1)

    amount_kopecks: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")

    status: Mapped[str] = mapped_column(String(16), default=OrderStatus.PENDING.value, index=True)

    provider: Mapped[str | None] = mapped_column(String(32), default=None)
    payment_method: Mapped[str | None] = mapped_column(String(16), default=None)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), default=None)
    redirect_url: Mapped[str | None] = mapped_column(Text, default=None)
    link_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), default=None
    )
    is_renewal: Mapped[bool] = mapped_column(Boolean, default=False)

    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)

    origin: Mapped[str] = mapped_column(String(16), default="site")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    plan: Mapped[Plan] = relationship()
    user: Mapped["User | None"] = relationship()

    @property
    def amount_rubles(self) -> Decimal:
        return Decimal(self.amount_kopecks) / 100


class BillingEvent(Base):

    __tablename__ = "billing_events"

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str | None] = mapped_column(String(32), default=None)
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, default=None
    )
    payload: Mapped[dict | None] = mapped_column(JSON, default=None)
    result: Mapped[str | None] = mapped_column(String(32), default=None)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class RecurringStatus(str, enum.Enum):

    PENDING = "pending"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RecurringSub(Base):

    __tablename__ = "recurring_subs"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_recurring_provider_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="platega")
    external_id: Mapped[str] = mapped_column(String(128), index=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_code: Mapped[str] = mapped_column(String(64))
    amount_kopecks: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    interval: Mapped[str] = mapped_column(String(16), default="month")

    status: Mapped[str] = mapped_column(
        String(16), default=RecurringStatus.PENDING.value, index=True
    )
    redirect_url: Mapped[str | None] = mapped_column(Text, default=None)

    next_charge_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    last_charge_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    last_charge_error: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    activated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship()

    @property
    def is_live(self) -> bool:
        return self.status in (
            RecurringStatus.PENDING.value,
            RecurringStatus.ACTIVE.value,
            RecurringStatus.PAST_DUE.value,
        )


class Referral(Base):

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(primary_key=True)

    inviter_telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True, default=None)
    inviter_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )

    invited_telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, index=True, default=None
    )
    invited_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )

    join_bonus_days: Mapped[int] = mapped_column(Integer, default=0)
    join_bonus_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    purchase_bonus_days: Mapped[int] = mapped_column(Integer, default=0)
    purchase_bonus_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)

    voided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    void_reason: Mapped[str | None] = mapped_column(Text, default=None)

    inviter: Mapped["User | None"] = relationship(foreign_keys=[inviter_user_id])
    invited: Mapped["User | None"] = relationship(foreign_keys=[invited_user_id])


class DayTransfer(Base):

    __tablename__ = "day_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    days: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(16), default="site")
    note: Mapped[str | None] = mapped_column(String(160), default=None)
    reverted_days: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)

    sender: Mapped[User] = relationship(foreign_keys=[from_user_id])
    recipient: Mapped[User] = relationship(foreign_keys=[to_user_id])


class DeliveryJob(Base):

    __tablename__ = "delivery_jobs"
    __table_args__ = (Index("ix_delivery_pending", "sent_at", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(16))
    template: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(255))

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, default=None
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, default=None
    )

    payload: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    next_attempt_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User | None"] = relationship()
    order: Mapped[Order | None] = relationship()


class TunnelFile(Base):

    __tablename__ = "tunnel_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(128), default="prostovpn-ru-sites.json")
    version: Mapped[str | None] = mapped_column(String(64), default=None)
    content: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class RateLimit(Base):

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)


class AuditLog(Base):

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), default=None
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(128), default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
