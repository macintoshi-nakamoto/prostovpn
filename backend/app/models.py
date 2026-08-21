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

# Насколько свежим должно быть рукопожатие, чтобы считать человека
# подключённым. WireGuard обновляет его примерно раз в две минуты, пока
# идёт трафик; три минуты — штатный интервал плюс запас на опоздавший обход.
HANDSHAKE_WINDOW = dt.timedelta(minutes=3)

# Платформы, у которых нет туннеля.
#
# Личный кабинет открывают в браузере, и это вход, а не устройство: VPN там
# не поднимается, конфига браузеру не выдаётся, отключать нечего. Пока такой
# вход считался устройством, человек, зашедший в кабинет с телефона и с
# ноутбука, съедал две трети тарифа на два браузера и не понимал, почему
# приложение на телефоне просит войти заново.
WEB_PLATFORMS = frozenset({"web", "site", "browser"})

# Приставка идентификатора «устройства», за которым стоит не приложение, а
# ключ AmneziaVPN для iPhone.
#
# Своего приложения под iOS нет, и человек вставляет в AmneziaVPN готовую
# ссылку `vpn://`. Ссылка — это отдельный пир, а пир заводится на
# устройство, поэтому место под iPhone занимает такая же строка в
# `user_keys`, как телефон с приложением: слот `ios-1`. Всё, что уже умеет
# система — учёт трафика, снятие пира по концу подписки, отзыв из панели, —
# работает с ним само, без второй ветки правил.
IOS_SLOT_PREFIX = "ios-"

# Сколько ключей AmneziaVPN человек может завести на одну учётку.
#
# Пять — это потолок, а не выдача: ключи заводятся по одному, кнопкой, и
# каждый следующий появляется, только когда за ним пришли. Потолок нужен
# затем же, зачем лимит устройств: один ключ — один пир, и без границы
# учётка раздавалась бы по цепочке знакомых, а трафик считался бы общим.
IOS_MAX_KEYS = 5


def is_ios_slot(device_id: str | None) -> bool:
    return (device_id or "").startswith(IOS_SLOT_PREFIX)


def ios_slot_number(device_id: str | None) -> int:
    """Номер ключа из идентификатора слота. Не слот — ноль."""
    if not is_ios_slot(device_id):
        return 0
    tail = (device_id or "")[len(IOS_SLOT_PREFIX) :]
    return int(tail) if tail.isdigit() else 0


def ios_slot(number: int) -> str:
    return f"{IOS_SLOT_PREFIX}{number}"


def sanitize_device_id(device_id: str | None) -> str | None:
    """
    Идентификатор установки, пришедший от клиента.

    Приставку `ios-` вырезаем: её выдаёт панель, и приложение, назвавшееся
    `ios-1`, заняло бы чужой по смыслу слот — тот, куда панель кладёт ключ
    для AmneziaVPN. Ничего страшнее путаницы в списках это не даёт (слот
    всё равно свой собственный), но путаница здесь дороже одной проверки.
    """
    value = (device_id or "").strip()
    if not value:
        return device_id
    while is_ios_slot(value):
        value = value[len(IOS_SLOT_PREFIX) :]
    return value or None


def is_device_platform(platform: str | None) -> bool:
    """
    Считается ли вход с этой платформы устройством.

    Неизвестная и пустая платформа — устройство: так входят старые версии
    приложений, не присылающие поле вовсе, и потерять их из списка хуже,
    чем показать лишнюю строку.
    """
    return (platform or "").strip().lower() not in WEB_PLATFORMS


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
    # Запасные порты того же узла, через запятую.
    #
    # Один порт — это одна точка отказа, и отказывает она не у нас, а у
    # оператора: 51820 known-порт WireGuard, и часть сетей его просто не
    # пропускает. Человек при этом видит исправное приложение, исправный
    # сервер и вечное «подключение». Узел слушает один порт, остальные
    # заворачиваются на него правилом DNAT (см. deploy/extra-ports.sh) —
    # здесь только список того, что реально доступно снаружи.
    alt_ports: Mapped[str] = mapped_column(String(120), default="", server_default="")

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

    def alt_port_list(self) -> list[int]:
        """Запасные порты числами, без основного и без мусора."""
        out: list[int] = []
        for chunk in (self.alt_ports or "").replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk.isdigit():
                continue
            value = int(chunk)
            if 0 < value < 65536 and value != self.port and value not in out:
                out.append(value)
        return out

    # Когда с сервера последний раз снимали счётчики трафика.
    traffic_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    traffic_error: Mapped[str | None] = mapped_column(Text, default=None)

    # Состояние узла по последней проверке. Отдельно от traffic_error,
    # потому что это разные вопросы: «сняли ли счётчики» и «может ли сюда
    # подключиться клиент». Второй важнее и его задают чаще.
    health_ok: Mapped[bool | None] = mapped_column(Boolean, default=None)
    health_summary: Mapped[str | None] = mapped_column(Text, default=None)
    health_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    # Снимок системных данных узла: ОС, ядро, процессор, память, диск,
    # версия AmneziaWG, состояние интерфейса. Снимком, а не запросом на
    # каждый показ: SSH к недоступной машине висит секундами, и открытие
    # списка серверов не должно от этого зависеть.
    facts: Mapped[dict | None] = mapped_column(JSON, default=None)

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
    #
    # Открытым текстом почта больше не хранится: это поле — наследие, его
    # чистит миграция, перекладывая адрес в пару ниже. Оставлено, чтобы
    # обновление не потеряло данные раньше, чем они переедут.
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, default=None)
    # Адрес под AES-GCM ключом SECRETS_KEY — прочитать его может только
    # панель, у которой есть ключ. Утечка базы адресов не отдаёт.
    email_enc: Mapped[str | None] = mapped_column(Text, default=None)
    # Слепой индекс (HMAC) для поиска точным совпадением: по нему повторная
    # покупка находит учётку, не расшифровывая ни одного адреса.
    email_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, default=None)
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
    # Личный безлимит, сильнее тарифного лимита.
    #
    # Отдельный флаг, а не None в поле выше, и это не дублирование. У поля
    # уже есть смысл: «своего лимита нет, бери из тарифа». Поэтому выдать
    # безлимит человеку на тарифе с лимитом было НЕЧЕМ: администратор
    # выбирал «Безлимит», панель записывала None, и лимит немедленно
    # откатывался к тарифному — выглядело как «не сохраняется», а человек
    # оставался ограничен.
    traffic_unlimited: Mapped[bool] = mapped_column(Boolean, default=False)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_reset_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    # Человек пользуется сервисом с iPhone, где своего приложения нет:
    # панель держит для него готовые ссылки `vpn://` под AmneziaVPN.
    #
    # Отдельный флаг, а не догадка по платформе входа. Ключ выдаётся до
    # первого входа — сразу после оплаты, — и вход с iPhone в браузере не
    # то же самое, что «этому человеку нужен ключ»: в кабинет заходят и с
    # чужого телефона. Ставится автоматически при покупке с iOS и руками
    # из панели, снимается только руками.
    ios_access: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Ключ отключён администратором.
    #
    # Отдельно от `ios_access`, и это не дублирование. Снять пометку — значит
    # разрешить человеку выдать ключ заново кнопкой в кабинете, то есть
    # отменить решение администратора через полминуты после того, как оно
    # принято. Отключённый ключ остаётся отключённым, пока его не включат
    # обратно: пир снят, кнопка выдачи не работает, в кабинете написано,
    # куда идти.
    ios_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

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
        """
        Подписка, по которой человек живёт ПРЯМО СЕЙЧАС: срок начался и ещё не
        кончился. По ней считаются тариф, лимиты и «есть ли доступ».

        Строго идущий период, а не «самый поздний из живых». Разница важна при
        смене тарифа: пока не дожиты дни старого тарифа, действует он, а не
        купленный «на потом». И наоборот — период, который начнётся завтра,
        доступа сегодня не даёт: has_access должен это видеть, иначе оплаченный
        будущий период открывал бы VPN до своего начала.

        Общий конец доступа (вместе с очередью) — в access_expires_at; сколько
        всего дней осталось — по нему, чтобы продление было видно сразу.
        """
        moment = now or utcnow()
        running = [
            s
            for s in self.subscriptions
            if not s.is_cancelled and s.starts_at <= moment < s.expires_at
        ]
        return max(running, key=lambda s: s.expires_at, default=None)

    def upcoming_subscriptions(self, now: dt.datetime | None = None) -> list["Subscription"]:
        """Оплаченная очередь: периоды, которые ещё не начались."""
        moment = now or utcnow()
        return sorted(
            (
                s
                for s in self.subscriptions
                if not s.is_cancelled and s.starts_at > moment and s.expires_at > moment
            ),
            key=lambda s: s.starts_at,
        )

    def access_expires_at(self, now: dt.datetime | None = None) -> dt.datetime | None:
        """
        Когда кончается весь оплаченный доступ — вместе с очередью.

        По нему кабинет и панель считают «осталось дней»: продление, встающее в
        очередь, обязано увеличивать это число сразу, иначе администратор жмёт
        «продлить» и не видит эффекта.
        """
        moment = now or utcnow()
        ends = [
            s.expires_at
            for s in self.subscriptions
            if not s.is_cancelled and s.expires_at > moment
        ]
        return max(ends, default=None)

    def access_days_left(self, now: dt.datetime | None = None) -> int | None:
        """Сколько всего дней доступа осталось; None — доступа нет."""
        moment = now or utcnow()
        end = self.access_expires_at(moment)
        return max(0, (end - moment).days) if end is not None else None

    def effective_traffic_limit(self, now: dt.datetime | None = None) -> int | None:
        """
        Сколько трафика человеку положено; None — безлимит.

        Порядок именно такой. Личный безлимит сильнее всего: его ставят
        руками конкретному человеку, и тарифный лимит его перебивать не
        должен. Дальше личное число, и только потом тариф.
        """
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
        """Сколько устройств разрешено. Без действующего тарифа — один."""
        plan = self.current_plan(now)
        return plan.device_limit if plan is not None else 1

    def ios_slot_numbers(self) -> list[int]:
        """
        Номера заведённых ключей AmneziaVPN — по строкам в `user_keys`.

        Считаем и отозванные строки. Отзыв — это снятый пир, а не удалённый
        ключ: после «отключить» и «включить» человек должен получить обратно
        те же ссылки, что лежат у него в Amnezia, а не новый набор. Удаляет
        ключ насовсем только явное удаление, и оно строки сносит.

        Номера не переиспользуются по кругу и не сдвигаются: удалили второй
        ключ из трёх — остаются первый и третий. Сдвиг переименовал бы
        третий во второй, и человек, глядя на «Ключ 2» в кабинете и в
        поддержке, говорил бы про разные пиры.
        """
        numbers = {ios_slot_number(key.device_id) for key in self.keys}
        return sorted(n for n in numbers if n > 0)

    def ios_slots(self, now: dt.datetime | None = None) -> list[str]:
        """
        Слоты ключей AmneziaVPN — сколько их у человека сейчас.

        Ключ `vpn://` — это один пир WireGuard, и поделить его между
        телефонами нельзя: сервер помнит у пира один адрес подключения, и
        второе устройство молча отбирает соединение у первого. Поэтому
        второй телефон — это второй ключ, а не тот же самый.

        Набор берётся из данных, а не из счётчика на учётке: строки в
        `user_keys` и есть то, что человеку выдано. Счётчик рядом с ними
        пришлось бы держать в согласии при каждом удалении и перевыпуске, и
        первое же расхождение молча сняло бы кому-нибудь работающий ключ.

        Больше `IOS_MAX_KEYS` не отдаём, даже если строк почему-то больше:
        лишние снимет `services.ios.sync`. Меньше одного — тоже: пометка
        `ios_access` без единого ключа означает «ключ положен, но ещё не
        заведён», и первый слот здесь как раз и появляется.

        Отключённые не в счёт — ни администратором (`ios_blocked`), ни самим
        человеком из списка устройств (`disconnected_at` на строках слота).
        Этот список читает раздача пиров (`ensure_keys` через
        `known_devices`), и пока отключённые слоты сюда попадали, продление
        подписки молча возвращало на узел пира, которого только что сняли.
        """
        if not self.ios_access or self.ios_blocked:
            return []
        rows: dict[int, list["UserKey"]] = {}
        for key in self.keys:
            number = ios_slot_number(key.device_id)
            if number > 0:
                rows.setdefault(number, []).append(key)
        if not rows:
            # Ключ положен, но ещё не заведён — первый слот появляется здесь.
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
        """Незакрытые и непросроченные входы — включая браузерные."""
        moment = now or utcnow()
        return [s for s in self.sessions if s.revoked_at is None and s.expires_at > moment]

    def device_sessions(self, now: dt.datetime | None = None) -> list["Session"]:
        """
        Живые входы с устройств — то, что считает лимит тарифа.

        Браузер сюда не попадает: см. WEB_PLATFORMS. Именно этот список
        видит человек в кабинете под заголовком «Устройства», и именно по
        нему считается «занято 2 из 3».
        """
        return [s for s in self.live_sessions(now) if s.is_device]

    def devices(self, now: dt.datetime | None = None) -> dict[str, "Session"]:
        """
        Живые устройства по их постоянному идентификатору установки.

        Ключ — `Session.device_key`: у приложения это его `device_id`, у
        старых версий, поля не присылающих, — пустая строка. Нужна раздаче
        пиров: пир заводится на устройство, а не на сессию, иначе каждый
        повторный вход занимал бы новый адрес в подсети.
        """
        found: dict[str, Session] = {}
        for session in self.device_sessions(now):
            current = found.get(session.device_key)
            if current is None or session.last_seen_at > current.last_seen_at:
                found[session.device_key] = session
        return found

    def is_locked_out(self, now: dt.datetime | None = None) -> bool:
        return self.locked_until is not None and self.locked_until > (now or utcnow())

    def set_email(self, address: str | None) -> None:
        """
        Единственное место, где почта попадает в базу.

        Три поля обязаны меняться вместе: шифротекст, слепой индекс и
        наследуемое открытое поле. Менять их врозь — значит однажды получить
        учётку, которую повторная покупка не находит, или адрес, который
        нельзя показать администратору.

        Ключа шифрования нет — адрес ложится открытым, как раньше: потерять
        почту клиента хуже, чем хранить её как хранили всегда. С ключом
        открытое поле остаётся пустым.
        """
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
        """
        Адрес открытым текстом — для письма, продления и карточки в панели.

        Шифротекст, который не читается (сменили ключ, залезли в базу), — это
        отсутствие адреса, а не падение всего списка пользователей.
        """
        if self.email_enc:
            from . import crypto

            try:
                return crypto.decrypt(self.email_enc)
            except crypto.SecretsUnavailable:
                return None
        return self.email

    def last_handshake(self) -> dt.datetime | None:
        """Самое свежее рукопожатие среди действующих пиров."""
        stamps = [
            key.last_handshake_at
            for key in self.keys
            if key.revoked_at is None and key.last_handshake_at is not None
        ]
        return max(stamps, default=None)

    def is_vpn_connected(self, now: dt.datetime | None = None) -> bool:
        """
        Подключён ли человек к VPN прямо сейчас.

        По рукопожатию пира, а не по сессии приложения. Это разные события:
        приложение может быть открыто с погашенным туннелем, а туннель —
        работать при закрытом приложении. Вопрос «пользуется ли он VPN»
        отвечается только со стороны узла.

        WireGuard обновляет рукопожатие примерно раз в две минуты, пока идёт
        трафик. Окно берём с запасом: три минуты покрывают штатный интервал,
        не выдавая отключившегося за подключённого дольше нужного.
        """
        stamp = self.last_handshake()
        if stamp is None:
            return False
        return stamp > (now or utcnow()) - HANDSHAKE_WINDOW

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
    """
    Конфиг конкретного устройства на конкретном сервере.

    Раньше ключ был один на пару «пользователь + сервер», и все устройства
    человека ходили одним пиром. Из-за этого «Отключить устройство» не могло
    отключить: погасить чужой токен — да, снять пира — нет, потому что пир
    общий и вместе с ним отвалились бы остальные. Теперь у каждого
    устройства свой пир, и отключение снимает ровно его.

    `device_id` — постоянный идентификатор установки, который присылает
    приложение. Пустая строка — «ключ учётки»: им пользуются версии
    приложений, поля ещё не присылающие, и он же выдаётся при заведении
    пользователя, когда устройств ещё нет.
    """

    __tablename__ = "user_keys"
    __table_args__ = (
        # Уникальность по тройке, а не по паре: у одного человека на одном
        # сервере столько пиров, сколько у него устройств.
        UniqueConstraint("user_id", "server_id", "device_id", name="uq_user_server_device_key"),
        # Один адрес в подсети принадлежит ровно одному пиру: AmneziaWG
        # маршрутизирует по allowed-ips, и второй пир с тем же адресом молча
        # отбирает его у первого — туннель поднимается, трафик не идёт.
        # Именно ИНДЕКС, а не UniqueConstraint: миграции досоздают на живой
        # таблице только индексы, ALTER TABLE ADD CONSTRAINT в SQLite нет.
        # Пустые адреса не мешают: несколько NULL уникальности не нарушают.
        Index("uq_user_keys_server_address", "server_id", "address", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    # Пустая строка, а не NULL, намеренно: в уникальном индексе NULL не равен
    # NULL, и «ключей учётки» на одну пару завелось бы сколько угодно.
    device_id: Mapped[str] = mapped_column(
        String(64), default="", server_default="", index=True
    )

    # Текст wg-quick либо ссылка vpn:// — приложение принимает оба вида.
    config: Mapped[str] = mapped_column(Text)
    public_key: Mapped[str | None] = mapped_column(String(64), default=None)
    address: Mapped[str | None] = mapped_column(String(64), default=None)

    # Счётчики пира с сервера. Абсолютные значения с момента поднятия
    # интерфейса: разницу между замерами копим в traffic_used_bytes.
    # Порт эндпоинта, отданный этому устройству в прошлый раз.
    #
    # Нужен, чтобы подбор порта не сбрасывался на каждом опросе и чтобы
    # сработавший порт закрепился за ключом: сменить его у человека, у
    # которого всё работает, — значит сломать работающее.
    endpoint_port: Mapped[int | None] = mapped_column(Integer, default=None)
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_handshake_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    traffic_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    # Ключ AmneziaVPN отключён самим человеком из списка устройств.
    #
    # Отдельно от revoked_at, потому что это разные вопросы: «пир снят с
    # узла» и «человек сам выключил этот ключ». Отзыв без пометки — дело
    # системы: кончилась подписка, выбран лимит — и выдача возвращает пира
    # при первом же поводе. С пометкой пир не возвращается ни продлением,
    # ни входом — только явным «включить», и тогда та же ссылка, что лежит
    # у человека в Amnezia, оживает как была.
    disconnected_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

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
    # Когда отправили напоминание о скором конце подписки.
    #
    # Без пометки обход слал бы его при каждом проходе, то есть раз в
    # несколько минут все три дня подряд. Одно письмо на подписку — и
    # продление обнуляет пометку само, потому что заводит новую строку.
    reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
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
    Вход приложения или браузера. Токен хранится только хэшем: утечка базы
    не должна отдавать живые доступы.
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

    @property
    def is_device(self) -> bool:
        """Занимает ли этот вход место в лимите устройств."""
        return is_device_platform(self.platform)

    @property
    def device_key(self) -> str:
        """
        Идентификатор установки для раздачи пиров.

        Пустая строка — приложение старой версии, поля не присылающее: все
        такие входы одного человека делят «ключ учётки», как было до
        появления пиров на устройство.
        """
        return (self.device_id or "").strip()


class PasswordReset(Base):
    """
    Разовая ссылка на смену пароля.

    В базе лежит ХЭШ токена, а не сам токен — ровно как у сессий. Смысл тот
    же: утёкшая база не должна давать возможность сменить пароль любому
    клиенту. Сам токен существует только в письме.

    Строку не удаляем после использования, а помечаем `used_at`: так видно,
    что ссылкой воспользовались, и повторное нажатие в письме честно скажет
    «ссылка уже использована» вместо «неверная ссылка».
    """

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    # Откуда просили. Нужен не для блокировок, а для разбора: «мне приходят
    # письма о сбросе, я их не просил» — обычное обращение в поддержку.
    requested_ip: Mapped[str | None] = mapped_column(String(64), default=None)

    user: Mapped[User] = relationship()

    def is_usable(self, now: dt.datetime | None = None) -> bool:
        moment = now or utcnow()
        return self.used_at is None and self.expires_at > moment


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

    # С какого устройства оформляли заказ. Нужно ровно для одного: покупку с
    # iPhone надо закрыть ключом AmneziaVPN, потому что приложения под iOS
    # нет и человеку после оплаты идти некуда. Определяется по браузеру в
    # момент создания заказа и запоминается — к приходу вебхука заголовков
    # уже нет, а решать надо тогда.
    platform: Mapped[str | None] = mapped_column(String(16), default=None)

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

    # Откуда пришёл заказ: site | bot | recurring. От этого зависит, куда
    # возвращать человека с платёжной формы и какие каналы доставки нужны.
    origin: Mapped[str] = mapped_column(String(16), default="site")

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


class RecurringStatus(str, enum.Enum):
    """
    Жизнь автосписания на стороне провайдера.

    `pending` — ссылка на привязку счёта создана, человек ещё не подтвердил.
    Дальше статусами управляют только вебхуки провайдера и явная отмена;
    сама панель их не выдумывает.
    """

    PENDING = "pending"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RecurringSub(Base):
    """
    Подписка с автосписанием у платёжного провайдера.

    Отдельная сущность от `Subscription` намеренно: та — оплаченный период
    доступа, эта — обещание провайдера списывать деньги по расписанию. Одно
    успешное списание порождает обычный заказ и обычный период доступа —
    вся выдача идёт тем же путём, что и разовая оплата, со всеми её
    рубежами.
    """

    __tablename__ = "recurring_subs"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_recurring_provider_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="platega")
    # Идентификатор подписки у провайдера: по нему приходят списания.
    external_id: Mapped[str] = mapped_column(String(128), index=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Код тарифа денормализован по той же причине, что и в Subscription:
    # тариф могут удалить, а история списаний должна остаться читаемой.
    plan_code: Mapped[str] = mapped_column(String(64))
    amount_kopecks: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    # month | year — интервал списаний у провайдера.
    interval: Mapped[str] = mapped_column(String(16), default="month")

    status: Mapped[str] = mapped_column(
        String(16), default=RecurringStatus.PENDING.value, index=True
    )
    # Ссылка на страницу привязки счёта: живёт, пока подписка pending, чтобы
    # человек мог вернуться и дооформить.
    redirect_url: Mapped[str | None] = mapped_column(Text, default=None)

    next_charge_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    last_charge_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    # Последняя беда со списанием — показывается человеку в кабинете.
    last_charge_error: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    activated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship()

    @property
    def is_live(self) -> bool:
        """Подписка, о которой стоит говорить в кабинете: ждёт или работает."""
        return self.status in (
            RecurringStatus.PENDING.value,
            RecurringStatus.ACTIVE.value,
            RecurringStatus.PAST_DUE.value,
        )


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

    # Данные, нужные конкретному письму и больше никому: например, разовый
    # токен ссылки на смену пароля. В базе от такой ссылки лежит только хэш,
    # поэтому взять её при отправке больше неоткуда.
    #
    # Отдельное поле, а не `order_id`: тот — внешний ключ на заказы, и
    # вставка постороннего значения туда просто не проходит.
    payload: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    next_attempt_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User | None"] = relationship()
    order: Mapped[Order | None] = relationship()


class TunnelFile(Base):
    """
    Файл раздельного туннелирования для AmneziaVPN — список сайтов, которые
    ходят мимо VPN.

    Содержимое лежит в базе, а не на диске. Файл маленький (список доменов),
    зато меняется часто: банки и госуслуги то перестают пускать зарубежные
    адреса, то начинают. В базе он переживает переустановку панели, ходит
    вместе с резервной копией и обновляется одной кнопкой — без выкладки
    файла на сервер и правки nginx.

    Строк в таблице может быть несколько: прошлые версии остаются историей,
    отдаётся всегда самая свежая включённая. Откатиться после неудачного
    списка — значит включить предыдущую строку, а не искать файл заново.
    """

    __tablename__ = "tunnel_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Как назвать файл при скачивании: человек кладёт его в AmneziaVPN.
    filename: Mapped[str] = mapped_column(String(128), default="prostovpn-ru-sites.json")
    # Метка версии для интерфейса: «от 17.08.2026» или своя строка.
    version: Mapped[str | None] = mapped_column(String(64), default=None)
    content: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


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
