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

    # Секрет для подписи служебных значений. На боевом обязательно свой.
    secret_key: str = "dev-insecure-change-me"

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
    traffic_sync_minutes: int = 15

    # Заполнить пустую базу демонстрационными данными при первом запуске.
    # На боевом выключается, иначе в базе появятся выдуманные люди.
    seed_demo: bool = False

    debug: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def settings() -> Settings:
    return Settings()
