"""Локальная база бота.

Здесь только то, что относится к Telegram: кто написал боту, кто под каким
логином вошёл и какие обращения прислал. Аккаунты, подписки и платежи
хранит панель — см. utils/panel.py.
"""

from pathlib import Path

import aiosqlite


DB_PATH = Path(__file__).resolve().parent / "database.db"


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        reg_date TEXT,
        last_visit TEXT,
        launches INTEGER DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions(
        user_id INTEGER PRIMARY KEY,
        panel_login TEXT NOT NULL,
        token TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS media(
        path TEXT PRIMARY KEY,
        file_id TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        panel_login TEXT,
        topic TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new',
        answer TEXT,
        created_at TEXT NOT NULL,
        answered_at TEXT
    )
    """,
    """
    -- Пригласительная ссылка с бесплатным периодом.
    --
    -- Живёт здесь, а не в панели: ссылка целиком телеграмная, и всё, что о
    -- ней нужно знать, — кто по ней пришёл. Дни начисляет панель обычным
    -- продлением, когда человек заведёт аккаунт.
    CREATE TABLE IF NOT EXISTS promos(
        code TEXT PRIMARY KEY,
        days INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        note TEXT
    )
    """,
    """
    -- Переход по ссылке. Строка на человека: вторая ссылка поверх первой
    -- не копится, а заменяет её, пока дни не начислены.
    CREATE TABLE IF NOT EXISTS promo_visits(
        user_id INTEGER PRIMARY KEY,
        code TEXT NOT NULL,
        visited_at TEXT NOT NULL,
        claimed_at TEXT,
        panel_login TEXT,
        days INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS star_payments(
        charge_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        panel_login TEXT,
        plan_code TEXT NOT NULL,
        amount INTEGER NOT NULL,
        currency TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new',
        created_at TEXT NOT NULL,
        done_at TEXT,
        note TEXT
    )
    """,
    """
    -- Письма вдогонку: зашёл и не завёл аккаунт, завёл и не подключился,
    -- подписка кончается.
    --
    -- Строка на пару «человек — повод», и это главное свойство таблицы:
    -- одно и то же напоминание не уходит дважды. `promised_days` помнит
    -- обещанное на словах — его начислит регистрация, а не рассылка;
    -- `expires_snapshot` помнит, до какого числа была подписка в момент
    -- письма: по нему видно, что человек продлил, и ему полагается бонус.
    CREATE TABLE IF NOT EXISTS nudges(
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        sent_at TEXT NOT NULL,
        promised_days INTEGER NOT NULL DEFAULT 0,
        expires_snapshot TEXT,
        claimed_at TEXT,
        claimed_days INTEGER,
        PRIMARY KEY (user_id, kind)
    )
    """,
)


async def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        for statement in SCHEMA:
            await db.execute(statement)

        await db.commit()
