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

    # Каталог с установщиками приложения (его же отдаёт nginx по /downloads/,
    # см. deploy/nginx.conf). Панель читает оттуда файл, чтобы посчитать его
    # размер и sha256 при публикации версии: без контрольной суммы приложение
    # отказывается ставить обновление, и «Обновить» падает ошибкой.
    downloads_dir: str = "/var/www/prosto-downloads"

    # Активный провайдер оплаты: mock | yookassa | cryptocloud.
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

    # Заказ без оплаты живёт сутки, дальше уходит в expired.
    order_ttl_hours: int = 24

    # --- доставка учётки ------------------------------------------------------

    # smtp | resend | console. console печатает письмо в лог без пароля —
    # для локальной разработки.
    mail_provider: str = "console"
    mail_from: str = "no-reply@example.com"
    mail_from_name: str = "Prosto"
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
