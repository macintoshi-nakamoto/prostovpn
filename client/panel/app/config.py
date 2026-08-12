"""Настройки панели: всё через переменные окружения, см. .env.example."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PANEL_", extra="ignore")

    # SQLite по умолчанию — панель поднимается одной командой без внешней БД.
    # На боевом VPS ставится postgresql+psycopg://user:pass@host/db
    database_url: str = "sqlite:///./panel.db"

    # Первый администратор создаётся при старте, если админов ещё нет.
    admin_login: str = "admin"
    admin_password: str = "admin"

    # Секрет для подписи cookie админки. На боевом обязательно свой:
    # со значением по умолчанию панель откажется слушать не на localhost.
    secret_key: str = "dev-insecure-change-me"

    # Сколько живёт токен приложения. Приложение продлевает его при каждом
    # запуске, поэтому активный пользователь не разлогинивается.
    client_token_days: int = 30

    # Валюта для статистики выручки — только для подписи в интерфейсе.
    currency: str = "RUB"

    debug: bool = False


@lru_cache
def settings() -> Settings:
    return Settings()
