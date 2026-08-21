"""Настройки панели: всё через переменные окружения, см. .env.example."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Значение, с которым панель поднимается локально и с которым её нельзя
# выпускать наружу. Проверяется на старте и в crypto.available().
INSECURE_DEFAULT_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PANEL_", extra="ignore")

    # SQLite по умолчанию — панель поднимается одной командой без внешней БД.
    # На боевом VPS ставится postgresql+psycopg://user:pass@host/db
    database_url: str = "sqlite:///./panel.db"

    # Первый администратор создаётся при старте, если админов ещё нет.
    admin_login: str = "admin"
    admin_password: str = "admin"

    # Секрет для подписи служебных значений. На боевом обязательно свой.
    secret_key: str = INSECURE_DEFAULT_SECRET
    # Ключ обратимого шифрования паролей клиентов (см. crypto.py). Отдельно
    # от secret_key: подпись куки меняют при компрометации не задумываясь, а
    # смена этого ключа делает нечитаемыми все сохранённые пароли.
    secrets_key: str = INSECURE_DEFAULT_SECRET

    # Сколько живёт токен приложения. Приложение продлевает его при каждом
    # запуске, поэтому активный пользователь не разлогинивается.
    client_token_days: int = 30
    # Токен веб-панели живёт меньше: с админского места уходят и забывают.
    admin_token_days: int = 7

    # Валюта для статистики выручки — только для подписи в интерфейсе.
    currency: str = "RUB"

    # Откуда пускаем веб-панель. Vite в разработке поднимается на 5173.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Как часто панель сама снимает счётчики трафика с серверов, минут.
    # 0 — не ходить автоматически, только по кнопке в панели.
    #
    # Оставлено ради существующих установок; новое значение задаётся
    # секундами, см. traffic_sync_seconds.
    traffic_sync_minutes: int = 0

    # Тот же обход, но в секундах. Одним заходом `awg show dump` снимаются и
    # расход трафика, и время последнего рукопожатия — а рукопожатие это и
    # есть ответ на вопрос «подключён ли человек прямо сейчас». Раз в
    # пятнадцать минут такой показатель бесполезен: половину времени он
    # показывал бы онлайн у отключившегося и оффлайн у подключившегося.
    #
    # Заодно здесь же срабатывает лимит трафика: между «выбрал гигабайты» и
    # «доступ закрылся» не должно проходить четверть часа.
    traffic_sync_seconds: int = 60

    @property
    def traffic_interval_seconds(self) -> int:
        """Итоговый интервал обхода. 0 — не ходить автоматически."""
        if self.traffic_sync_seconds > 0:
            return self.traffic_sync_seconds
        return self.traffic_sync_minutes * 60

    # Заполнить пустую базу демонстрационными данными при первом запуске.
    # На боевом выключается, иначе в базе появятся выдуманные люди.
    seed_demo: bool = False

    debug: bool = False

    # --- сайт и оплата --------------------------------------------------------

    # Публичный адрес сайта. Из него собираются ссылки возврата с платёжной
    # формы и адрес, на который провайдер шлёт вебхук.
    site_url: str = "http://localhost:8000"
    # Каталог собранного сайта. Пустая строка — раздавать не надо (сайт
    # стоит за nginx отдельно).
    site_dir: str = "../site"

    # Страница инструкции по установке. Пусто — берётся `site_url` + /guide.
    # Отдельной настройкой, потому что ссылку показывают в трёх местах —
    # кабинет, бот, письмо с доступом, — и переезд страницы не должен
    # означать правку в трёх проектах.
    guide_path: str = "/guide"
    guide_url: str = ""

    # Сайт — одностраничное приложение (React). Тогда на клиентские маршруты
    # (/login, /account, /faq) отдаётся index.html, а не 404: маршрутизация у
    # SPA своя, и по прямой ссылке сервер обязан вернуть тот же index.
    # По умолчанию выключено — старый многостраничный сайт так и раздаётся
    # пофайлово, с 404.html на опечатку в адресе.
    site_spa: bool = False

    # Каталог с установщиками приложения (его же отдаёт nginx по /downloads/,
    # см. deploy/nginx.conf). Панель читает оттуда файл, чтобы посчитать его
    # размер и sha256 при публикации версии: без контрольной суммы приложение
    # отказывается ставить обновление, и «Обновить» падает ошибкой.
    downloads_dir: str = "/var/www/prosto-downloads"

    # --- регистрация с сайта --------------------------------------------------

    # Самостоятельная регистрация: учётка заводится без оплаты и получает
    # пробный тариф. Выключается одной строкой, если раздавать пробный доступ
    # перестанет быть выгодно.
    signup_enabled: bool = True
    signup_plan_code: str = "trial"
    # Сколько учёток можно завести с одного адреса за окно. Без ограничения
    # бесплатный доступ раздаётся одним скриптом в сто рук.
    signup_max_per_ip: int = 3
    signup_window_minutes: int = 1440

    # Активный провайдер оплаты: mock | yookassa | cryptocloud | platega.
    payment_provider: str = "mock"

    # MockProvider: сам себе отправляет вебхук, чтобы весь путь оплаты можно
    # было пройти локально. На боевом сервере значение mock недопустимо.
    mock_delay_seconds: float = 2.0
    mock_secret: str = "mock-webhook-secret"

    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    # Адреса, с которых ЮKassa шлёт уведомления (их список опубликован в
    # документации). Пустая строка — не проверять по адресу, полагаться
    # только на сверку суммы и статуса через API.
    yookassa_ip_allowlist: str = (
        "185.71.76.0/27,185.71.77.0/27,77.75.153.0/25,77.75.156.11,77.75.156.35,"
        "77.75.154.128/25,2a02:5180::/32"
    )

    cryptocloud_api_key: str = ""
    cryptocloud_shop_id: str = ""
    # Секрет для проверки подписи уведомления CryptoCloud.
    cryptocloud_secret: str = ""

    # Platega: разовые платежи и подписки с автосписанием. Уведомления она
    # авторизует теми же X-MerchantId и X-Secret, что и наши запросы к ней.
    platega_merchant_id: str = ""
    platega_secret: str = ""
    platega_api_url: str = "https://app.platega.io"
    # Каким методом платят разовые заказы: 2 — СБП, 11 — карты, 13 — крипта,
    # 14 — SberPay. Подписки метод не выбирают, у них свой (6).
    platega_payment_method: int = 2

    # Куда возвращать человека после оплаты заказа, созданного из бота.
    telegram_bot_username: str = "prostovpnn_bot"

    # Заказ без оплаты живёт сутки, дальше уходит в expired.
    order_ttl_hours: int = 24

    # --- доставка учётки ------------------------------------------------------

    # smtp | smtpbz | resend | cloudflare | console. console печатает письмо в
    # лог без пароля — для локальной разработки.
    mail_provider: str = "console"
    mail_from: str = "no-reply@example.com"
    mail_from_name: str = "Prosto"
    # Куда писать человеку, если что-то пошло не так. Показывается на сайте,
    # в кабинете и в письмах; пустой — блок с почтой не рисуется вовсе.
    support_email: str = ""
    # Куда ведёт «Поддержка» в письмах. Телеграм-бот, а не почта: письмо
    # человек читает с телефона, и переписка в боте у нас и так основная.
    # Пусто — в письмах останется ссылка на почту поддержки.
    support_telegram: str = "https://t.me/prostovpnn_bot"
    # В теме письма намеренно нет слова VPN: российские почтовики режут такие
    # письма охотнее, а внутри всё равно только логин и пароль.
    mail_subject: str = "Ваш доступ к сервису Prosto"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False

    resend_api_key: str = ""

    # SMTP.bz — российский транзакционный отправитель. Ключ один и на API, и
    # на SMTP: у них это один и тот же секрет.
    smtpbz_api_key: str = ""

    # Cloudflare Email Service. Домен должен быть заведён в разделе
    # Email Sending дашборда: отправлять можно только с адреса того домена,
    # который там подтверждён, иначе API отвечает sending_disabled.
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""

    telegram_bot_token: str = ""

    # Как часто разгребается очередь доставки, секунд. 0 — не разгребать
    # (например, когда очередь крутит отдельный процесс).
    delivery_poll_seconds: int = 15
    delivery_max_attempts: int = 8

    # --- ограничение частоты --------------------------------------------------

    login_max_attempts: int = 5
    login_window_minutes: int = 15
    login_lock_minutes: int = 15

    order_max_per_hour: int = 10

    @property
    def guide_link(self) -> str:
        """Полный адрес инструкции по установке."""
        if self.guide_url.strip():
            return self.guide_url.strip()
        return f"{self.site_url.rstrip('/')}/{self.guide_path.strip('/')}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def yookassa_ips(self) -> list[str]:
        return [item.strip() for item in self.yookassa_ip_allowlist.split(",") if item.strip()]

    @property
    def is_production_ready(self) -> list[str]:
        """
        Что мешает выпускать эту конфигурацию наружу.

        Список проблем, а не булево: администратору полезнее увидеть все
        сразу, чем чинить их по одной, перезапуская панель.
        """
        problems: list[str] = []
        if self.secret_key == INSECURE_DEFAULT_SECRET:
            problems.append("PANEL_SECRET_KEY оставлен по умолчанию")
        if self.secrets_key == INSECURE_DEFAULT_SECRET:
            problems.append("PANEL_SECRETS_KEY оставлен по умолчанию — пароли не шифруются")
        if self.admin_password == "admin":
            problems.append("пароль администратора оставлен по умолчанию")
        if self.payment_provider == "mock":
            problems.append("PANEL_PAYMENT_PROVIDER=mock — оплата имитируется, деньги не приходят")
        if self.mail_provider == "console":
            problems.append("PANEL_MAIL_PROVIDER=console — письма с доступом не уходят")
        if self.seed_demo:
            problems.append("PANEL_SEED_DEMO=1 — в базу попадут выдуманные пользователи")
        return problems


@lru_cache
def settings() -> Settings:
    return Settings()
