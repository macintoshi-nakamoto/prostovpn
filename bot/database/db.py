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
)


async def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        for statement in SCHEMA:
            await db.execute(statement)

        await db.commit()
