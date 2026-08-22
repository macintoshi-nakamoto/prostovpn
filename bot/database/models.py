from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from database.db import DB_PATH
from utils import timeutils


@dataclass
class Session:
    """Вход в панель, привязанный к Telegram-аккаунту."""

    user_id: int
    panel_login: str
    token: str
    expires_at: datetime


@dataclass
class Ticket:
    id: int
    user_id: int
    panel_login: str | None
    topic: str
    message: str
    status: str
    answer: str | None
    created_at: datetime


@asynccontextmanager
async def _connect() -> AsyncIterator[aiosqlite.Connection]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


# --------------------------------------------------------------------------
# Пользователи Telegram
# --------------------------------------------------------------------------


async def knows_user(user_id: int) -> bool:
    """Писал ли человек боту раньше. Нужно для приглашений: дни дают за новых."""
    async with _connect() as db:
        cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))

        return await cursor.fetchone() is not None


async def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    stamp = timeutils.now_str()

    async with _connect() as db:
        cursor = await db.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user_id,),
        )

        if await cursor.fetchone():
            await db.execute(
                """
                UPDATE users
                SET username = ?,
                    first_name = ?,
                    last_visit = ?,
                    launches = launches + 1
                WHERE user_id = ?
                """,
                (username, first_name, stamp, user_id),
            )
        else:
            await db.execute(
                """
                INSERT INTO users (user_id, username, first_name, reg_date, last_visit)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, first_name, stamp, stamp),
            )

        await db.commit()


# --------------------------------------------------------------------------
# Сессии панели
# --------------------------------------------------------------------------


async def save_session(
    user_id: int,
    panel_login: str,
    token: str,
    expires_at: datetime,
) -> None:
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO sessions (user_id, panel_login, token, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                panel_login = excluded.panel_login,
                token = excluded.token,
                expires_at = excluded.expires_at,
                created_at = excluded.created_at
            """,
            (
                user_id,
                panel_login,
                token,
                timeutils.to_db(expires_at),
                timeutils.now_str(),
            ),
        )

        await db.commit()


async def get_session(user_id: int) -> Session | None:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE user_id = ?",
            (user_id,),
        )

        row = await cursor.fetchone()

        if not row:
            return None

        expires_at = timeutils.from_db(row["expires_at"])

        if expires_at <= timeutils.now():
            await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            await db.commit()
            return None

    return Session(
        user_id=row["user_id"],
        panel_login=row["panel_login"],
        token=row["token"],
        expires_at=expires_at,
    )


async def close_session(user_id: int) -> None:
    async with _connect() as db:
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.commit()


async def last_login(user_id: int) -> str | None:
    """Логин прошлого входа — чтобы не спрашивать его снова."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT panel_login FROM sessions WHERE user_id = ?",
            (user_id,),
        )

        row = await cursor.fetchone()

        if row:
            return row["panel_login"]

        cursor = await db.execute(
            "SELECT panel_login FROM tickets WHERE user_id = ? AND panel_login IS NOT NULL"
            " ORDER BY id DESC LIMIT 1",
            (user_id,),
        )

        row = await cursor.fetchone()

    return row["panel_login"] if row else None


# --------------------------------------------------------------------------
# Загруженные в Telegram файлы
# --------------------------------------------------------------------------


async def get_media(path: str) -> str | None:
    """file_id уже загруженной анимации: повторная отправка идёт без выгрузки."""
    async with _connect() as db:
        cursor = await db.execute("SELECT file_id FROM media WHERE path = ?", (path,))
        row = await cursor.fetchone()

    return row["file_id"] if row else None


async def save_media(path: str, file_id: str) -> None:
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO media (path, file_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                file_id = excluded.file_id,
                updated_at = excluded.updated_at
            """,
            (path, file_id, timeutils.now_str()),
        )

        await db.commit()


async def forget_media(path: str) -> None:
    async with _connect() as db:
        await db.execute("DELETE FROM media WHERE path = ?", (path,))
        await db.commit()


# --------------------------------------------------------------------------
# Обращения в поддержку
# --------------------------------------------------------------------------


def _ticket(row: aiosqlite.Row) -> Ticket:
    return Ticket(
        id=row["id"],
        user_id=row["user_id"],
        panel_login=row["panel_login"],
        topic=row["topic"],
        message=row["message"],
        status=row["status"],
        answer=row["answer"],
        created_at=timeutils.from_db(row["created_at"]),
    )


async def add_ticket(
    user_id: int,
    panel_login: str | None,
    topic: str,
    message: str,
) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            """
            INSERT INTO tickets (user_id, panel_login, topic, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, panel_login, topic, message, timeutils.now_str()),
        )

        await db.commit()
        ticket_id = cursor.lastrowid

    return ticket_id


async def last_tickets(user_id: int, limit: int = 5) -> list[Ticket]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM tickets WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

        rows = await cursor.fetchall()

    return [_ticket(row) for row in rows]


async def get_ticket(ticket_id: int) -> Ticket | None:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        row = await cursor.fetchone()

    return _ticket(row) if row else None


async def answer_ticket(ticket_id: int, answer: str) -> None:
    async with _connect() as db:
        await db.execute(
            """
            UPDATE tickets
            SET answer = ?, status = 'answered', answered_at = ?
            WHERE id = ?
            """,
            (answer, timeutils.now_str(), ticket_id),
        )

        await db.commit()
