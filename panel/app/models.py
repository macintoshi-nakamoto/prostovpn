"""
Схема базы: пользователи, тарифы, серверы, ключи, подписки, платежи, сессии.

Ключ живёт отдельной таблицей, а не полем пользователя: у одного
пользователя свой ключ на каждый сервер, и добавление сервера не должно
трогать самих пользователей.

Относительно исходной схемы панели добавлено то, без чего админка не может
вести учёт: публичный идентификатор пользователя, лимит и расход трафика,
тарифы с ценой и периодом, отдельный признак блокировки и история замеров
трафика по пирам.
"""

from __future__ import annotations

import datetime as dt
import enum
import secrets

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    """
    Время всегда наивное в UTC.

    SQLite не хранит часовой пояс: сохранив время с зоной, обратно получаем
    без неё, и сравнение падает с «can't compare offset-naive and
    offset-aware». Один вид времени во всей базе снимает вопрос и работает
    одинаково с SQLite и PostgreSQL.
    """
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# Алфавит без похожих символов: 0/O и 1/I/L человек путает, когда диктует
# идентификатор в поддержку.
_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_public_id() -> str:
    """Публичный идентификатор пользователя вида PV-7K3M-A29X."""
    block = lambda: "".join(secrets.choice(_ID_ALPHABET) for _ in range(4))  # noqa: E731
    return f"PV-{block()}-{block()}"


GB = 1024 ** 3


class Admin(Base):
    """Учётка для входа в саму панель — не имеет отношения к VPN."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class AdminSession(Base):
    """
    Сессия администратора в веб-панели.

    Панель — отдельный SPA, поэтому вместо cookie отдаём токен: он же
    ходит в заголовке Authorization и так же гасится при выходе.
    """

    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    admin: Mapped[Admin] = relationship()


class Provisioning(str, enum.Enum):
    """Откуда берётся конфиг пользователя для сервера."""

    # Один общий ключ на всех: так работает чужой сервер, где у нас нет root.
    SHARED = "shared"
    # Панель сама создаёт пира по SSH — нужен доступ к серверу.
    SSH = "ssh"


class Plan(Base):
    """
    Тариф: цена, срок и сколько трафика включено.

    Цена лежит на тарифе, а не на пользователе, чтобы календарь прибыли мог
    посчитать ожидаемые поступления: кто когда продлевается и на какую сумму.
    """

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    # None — безлимит. Отдельного флага нет: «нет лимита» и есть безлимит.
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Server(Base):
    """
    VPN-сервер. Добавленный и включённый сервер сразу виден всем
    приложениям: список отдаётся клиентским API целиком.
    """

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

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    provisioning: Mapped[Provisioning] = mapped_column(
        Enum(Provisioning, native_enum=False), default=Provisioning.SHARED
    )
    # Режим SHARED: готовый ключ vpn:// или wg-quick, который получают все.
    shared_config: Mapped[str | None] = mapped_column(Text, default=None)

    # Режим SSH: доступ к серверу и шаблон обфускации AmneziaWG.
    ssh_host: Mapped[str | None] = mapped_column(String(255), default=None)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str | None] = mapped_column(String(64), default=None)
    ssh_password: Mapped[str | None] = mapped_column(Text, default=None)
    ssh_key: Mapped[str | None] = mapped_column(Text, default=None)
    awg_template: Mapped[str | None] = mapped_column(Text, default=None)

    # Когда с сервера последний раз снимали счётчики трафика.
    traffic_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    traffic_error: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    keys: Mapped[list["UserKey"]] = relationship(back_populates="server", cascade="all, delete-orphan")


class User(Base):
    """Клиент сервиса: логин и пароль, с которыми он входит в приложение."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Публичный номер, который видит и называет клиент. Внутренний id в
    # интерфейсе не показываем: он выдаёт количество пользователей.
    public_id: Mapped[str] = mapped_column(String(24), unique=True, index=True, default=new_public_id)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Пароль показывается администратору один раз при создании; здесь лежит
    # только для того, чтобы его можно было продиктовать клиенту повторно.
    password_hint: Mapped[str | None] = mapped_column(String(128), default=None)
    name: Mapped[str | None] = mapped_column(String(128), default=None)
    contact: Mapped[str | None] = mapped_column(String(128), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    # Выключен администратором (пауза) — вход есть, серверов нет.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Заблокирован (бан) — вход запрещён совсем. Отдельно от паузы, потому что
    # это разные решения и разные причины.
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, default=None)
    blocked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    # Личный лимит трафика. None — берём из тарифа; тариф с None — безлимит.
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_reset_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    keys: Mapped[list["UserKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def active_subscription(self, now: dt.datetime | None = None) -> "Subscription | None":
        moment = now or utcnow()
        live = [s for s in self.subscriptions if s.expires_at > moment and not s.is_cancelled]
        return max(live, key=lambda s: s.expires_at, default=None)

    def effective_traffic_limit(self, now: dt.datetime | None = None) -> int | None:
        """Личный лимит важнее тарифного; None — безлимит."""
        if self.traffic_limit_bytes is not None:
            return self.traffic_limit_bytes
        sub = self.active_subscription(now)
        if sub is not None and sub.plan_ref is not None:
            return sub.plan_ref.traffic_limit_bytes
        return None

    def traffic_exhausted(self, now: dt.datetime | None = None) -> bool:
        limit = self.effective_traffic_limit(now)
        return limit is not None and self.traffic_used_bytes >= limit

    def has_access(self, now: dt.datetime | None = None) -> bool:
        """
        Доступ есть, если человек не забанен, не выключен, оплачен и не
        выбрал лимит трафика. Любое из четырёх — серверов не отдаём.
        """
        if self.is_blocked or not self.is_active:
            return False
        if self.active_subscription(now) is None:
            return False
        return not self.traffic_exhausted(now)


class UserKey(Base):
    """Конфиг конкретного пользователя на конкретном сервере."""

    __tablename__ = "user_keys"
    __table_args__ = (UniqueConstraint("user_id", "server_id", name="uq_user_server_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)

    # Текст wg-quick либо ссылка vpn:// — приложение принимает оба вида.
    config: Mapped[str] = mapped_column(Text)
    public_key: Mapped[str | None] = mapped_column(String(64), default=None)
    address: Mapped[str | None] = mapped_column(String(64), default=None)

    # Счётчики пира с сервера. Абсолютные значения с момента поднятия
    # интерфейса: разницу между замерами копим в traffic_used_bytes.
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_handshake_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    traffic_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship(back_populates="keys")
    server: Mapped[Server] = relationship(back_populates="keys")


class TrafficSample(Base):
    """
    Замер трафика пира. Храним прирост, а не абсолют: сервер могли
    перезагрузить, и счётчик обнулился — по приросту график не ломается.
    """

    __tablename__ = "traffic_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    delta_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sampled_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Subscription(Base):
    """Оплаченный период доступа."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Код тарифа денормализован: тариф могут переименовать или удалить, а в
    # истории подписки должно остаться, что человек покупал.
    plan: Mapped[str] = mapped_column(String(64), default="basic")
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL"), index=True, default=None
    )
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    # Ждём ли от человека следующую оплату — из этого строится ожидаемая
    # часть календаря прибыли.
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)

    starts_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="subscriptions")
    plan_ref: Mapped[Plan | None] = relationship()


class Payment(Base):
    """
    Поступление денег. Пока заводится вручную, но поля те же, что понадобятся
    автоматике после подключения оплаты: внешний идентификатор и способ.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True, default=None
    )
    # Numeric, а не float: деньги нельзя хранить в плавающей точке
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    method: Mapped[str | None] = mapped_column(String(64), default=None)
    external_id: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    paid_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)

    user: Mapped[User | None] = relationship(back_populates="payments")


class Session(Base):
    """
    Вход приложения. Токен хранится только хэшем: утечка базы не должна
    отдавать живые доступы.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform: Mapped[str | None] = mapped_column(String(32), default=None)
    app_version: Mapped[str | None] = mapped_column(String(32), default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship(back_populates="sessions")


class AppRelease(Base):
    """
    Версия приложения для конкретной платформы.

    Приложение спрашивает её при запуске и, если своя версия старее,
    показывает кнопку обновления. Переустанавливать вручную не нужно:
    ссылка на установщик приходит отсюда же.
    """

    __tablename__ = "app_releases"
    __table_args__ = (UniqueConstraint("platform", "version", name="uq_release_platform_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # windows, android, macos, linux, ios
    platform: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text)
    changelog: Mapped[str | None] = mapped_column(Text, default=None)
    # Размер и контрольная сумма — чтобы приложение проверило скачанное.
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    # Обязательное обновление: старую версию до сервиса не пускаем.
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    released_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Что администратор делал с пользователями — на случай разбирательств."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), default=None
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(128), default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
