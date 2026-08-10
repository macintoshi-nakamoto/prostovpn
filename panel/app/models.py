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


def new_uuid() -> str:
    """
    Идентификатор заказа.

    Строкой, а не нативным UUID: тип uuid есть в PostgreSQL и отсутствует в
    SQLite, а панель обязана подниматься на обеих. 36 символов канонической
    записи одинаково читаются в логах, в URL страницы успеха и в базе.
    """
    return str(uuid.uuid4())


GB = 1024 ** 3


def normalize_email(value: str | None) -> str | None:
    """
    Почта в базе всегда в нижнем регистре.

    В PostgreSQL это делал бы citext, но в SQLite такого типа нет. Приводим
    на входе сами — иначе `Ivan@mail.ru` и `ivan@mail.ru` заведут двух
    пользователей, и повторная покупка создаст вторую учётку вместо
    продления первой.
    """
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


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

    Денег в тарифе два поля, и это не дублирование по недосмотру.
    `price_kopecks` — источник истины: целые копейки, с ними считает сайт и
    платёжный провайдер, и в них невозможно потерять копейку на округлении.
    `price` — та же сумма рублями, оставленная ради календаря прибыли и
    остальной финансовой части, написанной до появления оплаты. Оба поля
    ставятся одним методом `set_price`, врозь их не трогают.
    """

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    price_kopecks: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    # None — безлимит. Отдельного флага нет: «нет лимита» и есть безлимит.
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)

    # Сколько стран и сколько одновременных устройств даёт тариф.
    server_limit: Mapped[int] = mapped_column(Integer, default=3)
    device_limit: Mapped[int] = mapped_column(Integer, default=3)
    # None — все страны. Иначе список кодов: ["NL", "DE", "FI"].
    allowed_regions: Mapped[list[str] | None] = mapped_column(JSON, default=None)

    # Короткая строка под ценой на сайте.
    tagline: Mapped[str | None] = mapped_column(String(160), default=None)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Тариф может быть живым, но не показываться на сайте: так делают
    # индивидуальные условия и тестовые периоды, которые выдаёт только админ.
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    def set_price(self, kopecks: int) -> None:
        """Единственное место, где меняется цена: два поля не расходятся."""
        self.price_kopecks = int(kopecks)
        self.price = Decimal(kopecks) / 100


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
    # Пароль под AES-GCM ключом SECRETS_KEY. Нужен ровно для одного: показать
    # его администратору, когда человек потерял письмо. Открытым текстом
    # пароль не лежит нигде — ни здесь, ни в очереди доставки, ни в логах.
    password_enc: Mapped[str | None] = mapped_column(Text, default=None)
    # Устаревшее поле: пароль открытым текстом. Новые учётки его не пишут,
    # старые чистит миграция. Оставлено, чтобы обновление не потеряло данные
    # раньше, чем они переедут в password_enc.
    password_hint: Mapped[str | None] = mapped_column(String(128), default=None)
    name: Mapped[str | None] = mapped_column(String(128), default=None)
    contact: Mapped[str | None] = mapped_column(String(128), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    # Почта — ключ, по которому повторная покупка находит человека и
    # продлевает подписку вместо создания второй учётки. Регистр приводится
    # к нижнему на записи, см. normalize_email.
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, default=None)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True, default=None)

    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

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

    # Защита от перебора пароля. Счётчик и замок живут на пользователе, а не
    # только в памяти процесса: перезапуск панели не должен обнулять защиту,
    # а за одним доменом может стоять несколько воркеров.
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

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

    def current_plan(self, now: dt.datetime | None = None) -> "Plan | None":
        sub = self.active_subscription(now)
        return sub.plan_ref if sub is not None else None

    def device_limit(self, now: dt.datetime | None = None) -> int:
        """Сколько устройств разрешено. Без действующего тарифа — один."""
        plan = self.current_plan(now)
        return plan.device_limit if plan is not None else 1

    def server_limit(self, now: dt.datetime | None = None) -> int | None:
        plan = self.current_plan(now)
        return plan.server_limit if plan is not None else None

    def allowed_regions(self, now: dt.datetime | None = None) -> list[str] | None:
        plan = self.current_plan(now)
        return plan.allowed_regions if plan is not None else None

    def live_sessions(self, now: dt.datetime | None = None) -> list["Session"]:
        """Незакрытые и непросроченные входы — они же «устройства»."""
        moment = now or utcnow()
        return [s for s in self.sessions if s.revoked_at is None and s.expires_at > moment]

    def is_locked_out(self, now: dt.datetime | None = None) -> bool:
        return self.locked_until is not None and self.locked_until > (now or utcnow())

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
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, default=None
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
    # Устройство глазами лимита тарифа. Приложение присылает свой постоянный
    # идентификатор установки: без него переустановка приложения на том же
    # телефоне считалась бы вторым устройством и съедала лимит.
    device_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    device_name: Mapped[str | None] = mapped_column(String(96), default=None)
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


# --- оплата с сайта -----------------------------------------------------------


class OrderStatus(str, enum.Enum):
    """
    Жизнь заказа.

    `pending` — форма заполнена, деньги ещё не пришли. Единственный переход
    в `paid` делает вебхук провайдера; возврат со страницы оплаты ничего не
    подтверждает и статус не трогает.
    """

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class Order(Base):
    """
    Намерение купить. Заводится до похода на платёжную форму, потому что
    вебхуку нужно, куда вернуться: провайдер знает только свой идентификатор
    платежа и сумму, а кому выдавать доступ — знает заказ.
    """

    __tablename__ = "orders"
    __table_args__ = (
        # Один платёж провайдера — один заказ. Если провайдер по ошибке
        # пришлёт свой payment_id второй раз с другим заказом, база не даст.
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

    # Сумма фиксируется в момент создания заказа и потом не пересчитывается:
    # человек согласился на конкретную цену, а тариф в панели могут поменять
    # между открытием формы и приходом вебхука.
    amount_kopecks: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")

    status: Mapped[str] = mapped_column(String(16), default=OrderStatus.PENDING.value, index=True)

    provider: Mapped[str | None] = mapped_column(String(32), default=None)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), default=None)
    redirect_url: Mapped[str | None] = mapped_column(Text, default=None)

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), default=None
    )
    # Продление существующей учётки, а не первая покупка. Определяется по
    # почте в момент выдачи и запоминается: письмо у них разное.
    is_renewal: Mapped[bool] = mapped_column(Boolean, default=False)

    # Почему заказ отклонён — например «сумма не совпала с тарифом».
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    plan: Mapped[Plan] = relationship()
    user: Mapped["User | None"] = relationship()

    @property
    def amount_rubles(self) -> Decimal:
        return Decimal(self.amount_kopecks) / 100


class BillingEvent(Base):
    """
    Принятое событие провайдера. Ключ идемпотентности и он же журнал.

    Провайдеры повторяют доставку десятки раз, пока не увидят 200, а иногда
    и после. Первичный ключ по идентификатору события — единственное, что
    надёжно превращает пять доставок в одну выдачу: проверка «а вдруг уже
    обработали» отдельным SELECT проигрывает гонку двум воркерам, вставка —
    нет.
    """

    __tablename__ = "billing_events"

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str | None] = mapped_column(String(32), default=None)
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, default=None
    )
    payload: Mapped[dict | None] = mapped_column(JSON, default=None)
    # Чем закончилась обработка: ok, duplicate, amount_mismatch, unknown_order.
    result: Mapped[str | None] = mapped_column(String(32), default=None)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class DeliveryJob(Base):
    """
    Задание на доставку учётки: письмо или сообщение в Telegram.

    Отдельная таблица, а не отправка прямо в вебхуке. Почтовый провайдер
    бывает недоступен, и попытка достучаться до него внутри транзакции либо
    держит блокировку на секундах ожидания, либо откатывает уже выданную
    подписку. Здесь же лежит и ретрай: письмо с доступом теряться не должно.

    Пароля в задании нет. Отправитель берёт его из `users.password_enc` и
    расшифровывает в момент отправки — открытым текстом он не появляется ни
    в базе очереди, ни в её логах.
    """

    __tablename__ = "delivery_jobs"
    __table_args__ = (Index("ix_delivery_pending", "sent_at", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(16))  # email | telegram
    template: Mapped[str] = mapped_column(String(32))  # credentials | renewed
    target: Mapped[str] = mapped_column(String(255))

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, default=None
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, default=None
    )

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    next_attempt_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User | None"] = relationship()
    order: Mapped[Order | None] = relationship()


class RateLimit(Base):
    """
    Счётчик попыток в скользящем окне: вход, создание заказов, вебхуки.

    В базе, а не в памяти: перезапуск процесса не должен обнулять защиту, а
    за одним адресом может стоять несколько воркеров uvicorn.
    """

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)


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
