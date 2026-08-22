import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


# Текст на пустом экране до кнопки «Начать» — первое, что видит человек.
# Без обещаний «без ограничений»: банк на верификации платёжной системы
# отклоняет такие формулировки, см. utils/texts.py.
BOT_DESCRIPTION = (
    "Prosto VPN - быстрый и надёжный VPN.\n\n"
    "В боте: личный кабинет, оплата подписки и поддержка. "
    "Логин и пароль общие с сайтом и приложением - один аккаунт на все устройства.\n\n"
    "Нажмите «Начать»."
)

# Подпись в профиле бота и в превью ссылки.
BOT_SHORT_DESCRIPTION = "Личный кабинет, тарифы и поддержка Prosto VPN"


@dataclass(frozen=True)
class PayMethod:
    code: str
    title: str
    ready: bool = False
    # Витрина без оплаты: каталог с ценами открывается и кнопки тарифов
    # кликабельны, но счёт не выставляется — способ ещё подключается.
    # Нужно платёжному провайдеру на согласовании: он смотрит, что каталог и
    # стоимость в боте есть, а не заглушку «скоро» вместо них.
    catalog_only: bool = False

    @property
    def shows_catalog(self) -> bool:
        return self.ready or self.catalog_only


@dataclass(frozen=True)
class SupportTopic:
    code: str
    title: str
    answer: str


SUPPORT_TOPICS: tuple[SupportTopic, ...] = (
    SupportTopic(
        code="connect",
        title="Не подключается",
        answer=(
            "Смените локацию в приложении и переподключитесь.\n"
            "Если не помогло - перезапустите приложение и проверьте, что подписка активна."
        ),
    ),
    SupportTopic(
        code="speed",
        title="Низкая скорость",
        answer=(
            "Выберите ближайший сервер - скорость зависит в основном от него.\n"
            "Замерьте скорость без VPN: иногда режет сам провайдер."
        ),
    ),
    SupportTopic(
        code="pay",
        title="Оплата не прошла",
        answer=(
            "Подписка продлевается сразу после оплаты.\n"
            "Если срок не изменился - откройте кабинет заново. Платежа нет в истории - напишите нам."
        ),
    ),
    SupportTopic(
        code="install",
        title="Установка приложения",
        answer=(
            "Скачайте приложение на сайте и войдите теми же логином и паролем.\n"
            "Windows может предупредить о неизвестном издателе - «Подробнее» → «Выполнить в любом случае»."
        ),
    ),
    SupportTopic(
        code="account",
        title="Проблема со входом",
        answer=(
            "Логин и пароль общие с сайтом и приложением, регистр пароля важен.\n"
            "Забыли пароль - напишите нам, восстановим доступ."
        ),
    ),
)


@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: tuple[int, ...] = field(default_factory=tuple)

    # Панель — общая база аккаунтов сайта, приложения и бота.
    panel_url: str = "https://prostovpn.cc"
    panel_admin_login: str = ""
    panel_admin_password: str = ""
    signup_plan: str = "trial"

    # Оплата картой включается токеном провайдера из @BotFather.
    provider_token: str = ""
    currency: str = "RUB"

    # Сколько звёзд просить за рубль цены тарифа: 1.0 — звезда равна рублю.
    stars_rate: float = 1.0

    # Имя бота — для реферальных ссылок вида t.me/<bot>?start=ref123.
    bot_username: str = "prostovpnn_bot"

    site_url: str = "https://prostovpn.cc"
    channel_url: str = "https://t.me/myprostovpn"
    # Инструкция по установке на сайте. Отдельной настройкой: ссылку
    # показывают и бот, и кабинет, и письмо с доступом.
    guide_url: str = "https://prostovpn.cc/guide"
    brand: str = "Prosto VPN"
    brand_version: str = "bot-1.0"


def _admin_ids() -> tuple[int, ...]:
    raw = os.getenv("ADMIN_IDS", "")
    ids = []

    for part in raw.replace(";", ",").split(","):
        part = part.strip()

        if part.lstrip("-").isdigit():
            ids.append(int(part))

    return tuple(ids)


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()

    if not token:
        raise RuntimeError("BOT_TOKEN не задан - заполните файл .env")

    return Config(
        token=token,
        admin_ids=_admin_ids(),
        panel_url=os.getenv("PANEL_URL", "https://prostovpn.cc").strip().rstrip("/"),
        panel_admin_login=os.getenv("PANEL_ADMIN_LOGIN", "").strip(),
        panel_admin_password=os.getenv("PANEL_ADMIN_PASSWORD", "").strip(),
        signup_plan=os.getenv("SIGNUP_PLAN", "trial").strip() or "trial",
        provider_token=os.getenv("PROVIDER_TOKEN", "").strip(),
        currency=os.getenv("CURRENCY", "RUB").strip() or "RUB",
        stars_rate=_float("STARS_RATE", 1.0),
        bot_username=os.getenv("BOT_USERNAME", "prostovpnn_bot").strip().lstrip("@"),
        site_url=os.getenv("SITE_URL", "https://prostovpn.cc").strip(),
        channel_url=os.getenv("CHANNEL_URL", "https://t.me/myprostovpn").strip(),
        guide_url=os.getenv("GUIDE_URL", "https://prostovpn.cc/guide").strip(),
    )


config = load_config()


def topic_by_code(code: str) -> SupportTopic | None:
    for topic in SUPPORT_TOPICS:
        if topic.code == code:
            return topic

    return None


def card_payments_enabled() -> bool:
    return bool(config.provider_token)


def payment_methods() -> tuple[PayMethod, ...]:
    """Способы оплаты. Неготовые остаются на экране - но честно помечены."""
    methods = [
        # СБП первым: оплата деньгами - основной путь, звёзды - запасной.
        PayMethod("sbp", "СБП", ready=True),
        PayMethod("stars", "Telegram Stars", ready=True),
        PayMethod("crypto", "Криптовалюта", ready=True),
    ]

    if card_payments_enabled():
        methods.append(PayMethod("card", "Банковская карта", ready=True))

    return tuple(methods)


def method_by_code(code: str) -> PayMethod | None:
    for method in payment_methods():
        if method.code == code:
            return method

    return None
