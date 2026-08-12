"""
Схема базы: пользователи, серверы, ключи, подписки, платежи, сессии.

Ключ живёт отдельной таблицей, а не полем пользователя: у одного
пользователя свой ключ на каждый сервер, и добавление сервера не должно
трогать самих пользователей.
"""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
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


class Admin(Base):
    """Учётка для входа в саму панель — не имеет отношения к VPN."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Provisioning(str, enum.Enum):
    """Откуда берётся конфиг пользователя для сервера."""

    # Один общий ключ на всех: так работает чужой сервер, где у нас нет root.
    SHARED = "shared"
    # Панель сама создаёт пира по SSH — нужен доступ к серверу.
    SSH = "ssh"


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

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    keys: Mapped[list["UserKey"]] = relationship(back_populates="server", cascade="all, delete-orphan")


class User(Base):
    """Клиент сервиса: логин и пароль, с которыми он входит в приложение."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
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

    def has_access(self, now: dt.datetime | None = None) -> bool:
        return self.is_active and self.active_subscription(now) is not None


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

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship(back_populates="keys")
    server: Mapped[Server] = relationship(back_populates="keys")


class Subscription(Base):
    """Оплаченный период доступа."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(64), default="basic")
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="subscriptions")


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
