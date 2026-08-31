from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PANEL_", extra="ignore")

    database_url: str = "sqlite:///./panel.db"

    admin_login: str = "admin"
    admin_password: str = "admin"

    secret_key: str = INSECURE_DEFAULT_SECRET
    secrets_key: str = INSECURE_DEFAULT_SECRET

    client_token_days: int = 30
    admin_token_days: int = 7

    subscription_token_days: int = 180
    subscription_url: str = ""

    currency: str = "RUB"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    traffic_sync_minutes: int = 0

    traffic_sync_seconds: int = 60

    @property
    def traffic_interval_seconds(self) -> int:
        if self.traffic_sync_seconds > 0:
            return self.traffic_sync_seconds
        return self.traffic_sync_minutes * 60

    seed_demo: bool = False

    debug: bool = False


    site_url: str = "http://localhost:8000"
    site_dir: str = "../site"

    guide_path: str = "/guide"
    guide_url: str = ""

    site_spa: bool = False

    downloads_dir: str = "/var/www/prosto-downloads"


    signup_enabled: bool = True
    signup_plan_code: str = "trial"
    signup_max_per_ip: int = 3
    signup_window_minutes: int = 1440

    payment_provider: str = "mock"

    mock_delay_seconds: float = 2.0
    mock_secret: str = "mock-webhook-secret"

    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_ip_allowlist: str = (
        "185.71.76.0/27,185.71.77.0/27,77.75.153.0/25,77.75.156.11,77.75.156.35,"
        "77.75.154.128/25,2a02:5180::/32"
    )

    cryptocloud_api_key: str = ""
    cryptocloud_shop_id: str = ""
    cryptocloud_secret: str = ""

    # TON: адрес кошелька-кассы, читаем только входящие через toncenter.
    ton_wallet_address: str = ""
    ton_api_url: str = "https://toncenter.com/api/v2"
    ton_api_key: str = ""
    ton_rate_spread: float = 0.02
    ton_poll_seconds: int = 15

    platega_merchant_id: str = ""
    platega_secret: str = ""
    platega_api_url: str = "https://app.platega.io"
    platega_payment_method: int = 2

    telegram_bot_username: str = "prostovpnn_bot"


    referral_join_days: int = 2
    referral_purchase_days: int = 5
    referral_join_daily_limit: int = 10

    order_ttl_hours: int = 24


    mail_provider: str = "console"
    mail_from: str = "no-reply@example.com"
    mail_from_name: str = "Prosto"
    support_email: str = ""
    support_telegram: str = "https://t.me/prostovpnn_bot"
    mail_subject: str = "Ваш доступ к сервису Prosto"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False

    resend_api_key: str = ""

    smtpbz_api_key: str = ""

    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""

    telegram_bot_token: str = ""

    delivery_poll_seconds: int = 15
    delivery_max_attempts: int = 8


    login_max_attempts: int = 5
    login_window_minutes: int = 15
    login_lock_minutes: int = 15

    order_max_per_hour: int = 10

    @property
    def guide_link(self) -> str:
        if self.guide_url.strip():
            return self.guide_url.strip()
        return f"{self.site_url.rstrip('/')}/{self.guide_path.strip('/')}"

    @property
    def subscription_base(self) -> str:
        return (self.subscription_url.strip() or self.site_url).rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def yookassa_ips(self) -> list[str]:
        return [item.strip() for item in self.yookassa_ip_allowlist.split(",") if item.strip()]

    @property
    def is_production_ready(self) -> list[str]:
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
