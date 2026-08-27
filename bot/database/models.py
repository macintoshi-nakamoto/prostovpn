from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

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
            # Стираем мёртвый токен, но логин ОСТАВЛЯЕМ.
            #
            # Раньше строка удалялась целиком, и вместе с ней пропадал ответ
            # на вопрос «кому продлевать»: последний рубеж last_login ищет
            # логин именно здесь. Человек с протухшей сессией платил
            # звёздами, а продлевать оказывалось некому — деньги списаны,
            # доступа нет. Явный выход из учётки по-прежнему удаляет строку
            # целиком, см. close_session: это осознанное «забудьте меня».
            await db.execute("UPDATE sessions SET token = '' WHERE user_id = ?", (user_id,))
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


# --------------------------------------------------------------------------
# Оплата звёздами
#
# Своя запись о каждом платеже нужна по трём причинам, и все три про деньги.
#
# Первая — повторы. Telegram присылает апдейт заново, если бот не успел его
# подтвердить: перезапуск в неудачный момент, обрыв сети. Без отметки о том,
# что этот платёж уже обработан, повтор продлевал бы подписку второй раз и
# писал второй платёж в кассу.
#
# Вторая — возврат. Вернуть звёзды можно только по идентификатору платежа,
# и если он нигде не сохранён, возвращать нечего.
#
# Третья — разбор. Заказ (Order) при оплате звёздами не создаётся, и когда
# человек говорит «я заплатил», единственным доказательством остаётся эта
# строка.
# --------------------------------------------------------------------------


async def claim_star_payment(
    charge_id: str,
    user_id: int,
    plan_code: str,
    amount: int,
    currency: str,
    panel_login: str | None,
) -> bool:
    """
    Забирает платёж в работу. False — его уже забрали раньше.

    Проверка и запись — одним оператором: два апдейта об одной оплате могут
    прийти одновременно, и «сначала посмотреть, потом вставить» их не
    развело бы.
    """
    async with _connect() as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO star_payments
                (charge_id, user_id, panel_login, plan_code, amount, currency, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'new', ?)
            """,
            (charge_id, user_id, panel_login, plan_code, amount, currency, timeutils.now_str()),
        )

        await db.commit()

        return cursor.rowcount > 0


async def finish_star_payment(charge_id: str, status: str, note: str | None = None) -> None:
    """Чем закончилось: «done» — подписка продлена, «failed» — разбирать руками."""
    async with _connect() as db:
        await db.execute(
            "UPDATE star_payments SET status = ?, done_at = ?, note = ? WHERE charge_id = ?",
            (status, timeutils.now_str(), note, charge_id),
        )

        await db.commit()


async def star_payment(charge_id: str) -> dict | None:
    """Строка платежа как есть — для разбора и для возврата."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM star_payments WHERE charge_id = ?", (charge_id,)
        )
        row = await cursor.fetchone()

    return dict(row) if row else None


async def stuck_star_payments(limit: int = 50) -> list[dict]:
    """
    Платежи, которые не довели до подписки. Их разбирают руками.

    Завершённые и возвращённые сюда не попадают: список нужен как рабочая
    очередь, а не как история — иначе разобранное копится и его перестают
    читать.
    """
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM star_payments WHERE status NOT IN ('done', 'refunded')"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


# --------------------------------------------------------------------------
# Пригласительные ссылки с бесплатным периодом
# --------------------------------------------------------------------------
#
# Ссылка одна на всех, дни — каждому по разу. Поэтому здесь две таблицы:
# сама ссылка со сроком жизни и отметка о переходе, по одной на человека.
# Дни начисляет панель; здесь только память о том, кому они положены.


@dataclass
class Promo:
    code: str
    days: int
    expires_at: datetime
    note: str | None = None

    @property
    def alive(self) -> bool:
        return self.expires_at > timeutils.now()


def _promo(row: aiosqlite.Row) -> Promo:
    return Promo(
        code=row["code"],
        days=row["days"],
        expires_at=timeutils.from_db(row["expires_at"]),
        note=row["note"],
    )


async def create_promo(code: str, days: int, ttl_days: int, note: str | None = None) -> Promo:
    """Заводит ссылку. Повторный вызов с тем же кодом продлевает её."""
    now = timeutils.now()
    expires_at = timeutils.to_db(now + timedelta(days=ttl_days))

    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO promos(code, days, expires_at, created_at, note)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                days = excluded.days,
                expires_at = excluded.expires_at,
                note = excluded.note
            """,
            (code, days, expires_at, timeutils.to_db(now), note),
        )
        await db.commit()

    return Promo(code=code, days=days, expires_at=timeutils.from_db(expires_at), note=note)


async def get_promo(code: str) -> Promo | None:
    """Ссылка как она есть — вместе с истёкшей: срок проверяет вызывающий."""
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM promos WHERE code = ?", (code,))
        row = await cursor.fetchone()

    return _promo(row) if row else None


async def remember_promo(user_id: int, code: str) -> None:
    """
    Отмечает переход. Дни не начисляет — их даёт регистрация.

    Уже начисленное не трогаем: иначе второй переход по той же ссылке
    открывал бы бонус заново.
    """
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT claimed_at FROM promo_visits WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()

        if row and row["claimed_at"]:
            return

        await db.execute(
            """
            INSERT INTO promo_visits(user_id, code, visited_at)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                code = excluded.code,
                visited_at = excluded.visited_at
            """,
            (user_id, code, timeutils.now_str()),
        )
        await db.commit()


async def pending_promo(user_id: int) -> Promo | None:
    """
    Ссылка, по которой этот человек пришёл и дни ещё не получил.

    Истёкшая ссылка засчитывается, если переход был меньше суток назад:
    иначе тот, кто открыл её за минуту до конца срока и не успел придумать
    пароль, терял бонус на ровном месте.
    """
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT v.visited_at, p.*
            FROM promo_visits AS v
            JOIN promos AS p ON p.code = v.code
            WHERE v.user_id = ? AND v.claimed_at IS NULL
            """,
            (user_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        return None

    promo = _promo(row)

    if promo.alive:
        return promo

    visited = timeutils.from_db(row["visited_at"])

    return promo if timeutils.now() - visited < timedelta(days=1) else None


async def claim_promo(user_id: int, panel_login: str, days: int) -> None:
    """Дни начислены — переход закрываем, чтобы не начислить второй раз."""
    async with _connect() as db:
        await db.execute(
            """
            UPDATE promo_visits
            SET claimed_at = ?, panel_login = ?, days = ?
            WHERE user_id = ? AND claimed_at IS NULL
            """,
            (timeutils.now_str(), panel_login, days, user_id),
        )
        await db.commit()


async def promo_stats(code: str) -> tuple[int, int]:
    """Сколько переходов по ссылке и сколько из них дошло до аккаунта."""
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) AS visits,
                   COUNT(claimed_at) AS claims
            FROM promo_visits WHERE code = ?
            """,
            (code,),
        )
        row = await cursor.fetchone()

    return (row["visits"], row["claims"]) if row else (0, 0)


async def all_promos(limit: int = 20) -> list[Promo]:
    """Все ссылки, свежие сверху."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM promos ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()

    return [_promo(row) for row in rows]


# --------------------------------------------------------------------------
# Письма вдогонку
# --------------------------------------------------------------------------
#
# Три повода написать первым: человек зашёл и не завёл аккаунт, завёл и ни
# разу не подключился, подписка кончается. Каждое напоминание уходит один
# раз — за это отвечает первичный ключ (user_id, kind), а не проверка в коде.


@dataclass
class Nudge:
    user_id: int
    kind: str
    sent_at: datetime
    promised_days: int
    expires_snapshot: datetime | None
    claimed_at: datetime | None
    claimed_days: int | None

    @property
    def open(self) -> bool:
        """Обещание, которое ещё не выполнено."""
        return self.claimed_at is None


@dataclass
class Candidate:
    """Человек из базы бота и логин, под которым он известен панели."""

    user_id: int
    first_seen: datetime
    last_visit: datetime | None
    login: str | None


def _nudge(row: aiosqlite.Row) -> Nudge:
    return Nudge(
        user_id=row["user_id"],
        kind=row["kind"],
        sent_at=timeutils.from_db(row["sent_at"]),
        promised_days=row["promised_days"],
        expires_snapshot=(
            timeutils.from_db(row["expires_snapshot"]) if row["expires_snapshot"] else None
        ),
        claimed_at=timeutils.from_db(row["claimed_at"]) if row["claimed_at"] else None,
        claimed_days=row["claimed_days"],
    )


async def audience() -> list[Candidate]:
    """
    Все, кто писал боту, вместе с логином — если он вообще известен.

    Логин ищем в трёх местах сразу, и порядок здесь важен: живая сессия,
    потом закрытый подарок, потом обращение в поддержку. Человек мог войти
    год назад, выйти и с тех пор только писать в поддержку — для рассылки он
    всё равно «с аккаунтом», и предлагать ему регистрацию заново нельзя.
    """
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT u.user_id,
                   u.reg_date,
                   u.last_visit,
                   COALESCE(s.panel_login, v.panel_login, t.panel_login) AS login
            FROM users AS u
            LEFT JOIN sessions AS s ON s.user_id = u.user_id
            LEFT JOIN promo_visits AS v
                   ON v.user_id = u.user_id AND v.panel_login IS NOT NULL
            LEFT JOIN (
                SELECT user_id, panel_login
                FROM tickets
                WHERE panel_login IS NOT NULL
                GROUP BY user_id
            ) AS t ON t.user_id = u.user_id
            """
        )
        rows = await cursor.fetchall()

    people = []

    for row in rows:
        if not row["reg_date"]:
            continue

        people.append(
            Candidate(
                user_id=row["user_id"],
                first_seen=timeutils.from_db(row["reg_date"]),
                last_visit=timeutils.from_db(row["last_visit"]) if row["last_visit"] else None,
                login=row["login"],
            )
        )

    return people


async def get_nudge(user_id: int, kind: str) -> Nudge | None:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM nudges WHERE user_id = ? AND kind = ?", (user_id, kind)
        )
        row = await cursor.fetchone()

    return _nudge(row) if row else None


async def remember_nudge(
    user_id: int,
    kind: str,
    promised_days: int = 0,
    expires_snapshot: datetime | None = None,
) -> None:
    """
    Отмечает отправленное напоминание.

    Повторная запись затирает прежнюю целиком — так напоминание о конце
    подписки уходит и в следующий раз, когда подписка снова подойдёт к концу.
    Решает, пора ли, вызывающий: здесь только память.
    """
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO nudges(user_id, kind, sent_at, promised_days, expires_snapshot)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(user_id, kind) DO UPDATE SET
                sent_at = excluded.sent_at,
                promised_days = excluded.promised_days,
                expires_snapshot = excluded.expires_snapshot,
                claimed_at = NULL,
                claimed_days = NULL
            """,
            (
                user_id,
                kind,
                timeutils.now_str(),
                promised_days,
                timeutils.to_db(expires_snapshot) if expires_snapshot else None,
            ),
        )
        await db.commit()


async def claim_nudge(user_id: int, kind: str, days: int) -> bool:
    """
    Закрывает обещание. False — его уже закрыли раньше.

    Проверка и запись одним оператором: регистрация и обходчик рассылки
    могут дойти до одного обещания одновременно, и «сначала посмотреть,
    потом обновить» подарило бы дни дважды.
    """
    async with _connect() as db:
        cursor = await db.execute(
            """
            UPDATE nudges
            SET claimed_at = ?, claimed_days = ?
            WHERE user_id = ? AND kind = ? AND claimed_at IS NULL
            """,
            (timeutils.now_str(), days, user_id, kind),
        )
        await db.commit()

        return cursor.rowcount > 0


async def promised_days(user_id: int, kind: str) -> int:
    """Сколько дней обещано и ещё не выдано. 0 — обещаний нет."""
    nudge = await get_nudge(user_id, kind)

    return nudge.promised_days if nudge and nudge.open else 0
