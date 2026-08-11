"""
Мягкие миграции схемы.

Alembic здесь избыточен: панель ставится одним человеком на один сервер, а
единственный вид изменений, который встречался за всю её жизнь, — новая
колонка или новая таблица. Поэтому вместо цепочки ревизий сравниваем то,
что описано в моделях, с тем, что есть в базе, и досоздаём недостающее.

Что этот механизм намеренно не делает: не переименовывает, не удаляет и не
меняет тип. Такие изменения редки, опасны и должны выполняться руками, с
бэкапом и осознанным решением, а не молча при старте.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session as OrmSession

from .models import Base, Plan, User, UserKey, utcnow

log = logging.getLogger("panel.migrations")


def run(engine: Engine) -> None:
    """Создаёт недостающие таблицы, колонки и индексы, потом чинит данные."""
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    # Дубли адресов разводим до индексов, а не в backfill: тот идёт уже после
    # создания индексов, и уникальный индекс по (server_id, address) на такой
    # базе просто не встал бы — _create_missing_indexes только пишет об этом
    # в журнал и идёт дальше.
    _dedupe_key_addresses(engine)
    _create_missing_indexes(engine)


def backfill(db: OrmSession) -> None:
    """
    Правки данных, которые нельзя выразить в DDL.

    Отдельно от структуры и после неё: часть из них требует ключа шифрования
    и питоновского кода, а не одного UPDATE.
    """
    _backfill_plan_kopecks(db)
    _encrypt_legacy_passwords(db)


# --- структура ----------------------------------------------------------------


def _literal_default(column, dialect_name: str) -> str | None:
    """Скалярное значение по умолчанию в виде литерала SQL."""
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, bool):
        # SQLite понимает TRUE с версии 3.23, но 1/0 читается везде.
        return ("1" if value else "0") if dialect_name == "sqlite" else ("true" if value else "false")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _add_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    dialect = engine.dialect
    quote = dialect.identifier_preparer.quote

    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue

            type_sql = column.type.compile(dialect)
            parts = [f"{quote(column.name)} {type_sql}"]
            default = _literal_default(column, dialect.name)

            if default is not None:
                parts.append(f"DEFAULT {default}")
            if not column.nullable:
                if default is None:
                    # NOT NULL без значения по умолчанию невозможно добавить в
                    # непустую таблицу. Колонку заводим, ограничение оставляем
                    # администратору: молча портить схему хуже, чем сказать.
                    log.warning(
                        "колонка %s.%s добавлена без NOT NULL: нет значения по умолчанию",
                        table.name,
                        column.name,
                    )
                else:
                    parts.append("NOT NULL")

            sql = f"ALTER TABLE {quote(table.name)} ADD COLUMN {' '.join(parts)}"
            with engine.begin() as conn:
                conn.execute(text(sql))
            log.info("миграция: %s.%s", table.name, column.name)


def _create_missing_indexes(engine: Engine) -> None:
    """
    Индексы для колонок, добавленных выше.

    `create_all` расставляет их только при создании таблицы: колонка,
    приехавшая в уже существующую, осталась бы без индекса — и уникальность
    почты, на которой держится продление вместо второй учётки, не
    проверялась бы вовсе.
    """
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in existing:
                continue
            try:
                with engine.begin() as conn:
                    index.create(conn)
                log.info("миграция: индекс %s", index.name)
            except Exception as exc:  # pragma: no cover - зависит от данных
                # Уникальный индекс не встанет, если в базе уже есть дубли.
                # Это повод разобраться руками, а не повод не запускаться.
                log.error("индекс %s не создан: %s", index.name, exc)


def _dedupe_key_addresses(engine: Engine) -> None:
    """
    Разводит ключи, которым на одном сервере достался один адрес.

    До появления уникального индекса две одновременные выдачи успевали
    выбрать один и тот же свободный адрес: на узле адрес принадлежит ровно
    одному пиру, и второй молча отбирал его у первого. Адрес оставляем тому,
    кто на узле его скорее всего и держит — живому и самому позднему, —
    остальные переселяем на свободные и отправляем на перевыпуск: пустой
    конфиг и `revoked_at` заставят ensure_keys выдать конфиг заново, а старый
    пир снимет issue_key по сохранённому публичному ключу.
    """
    if not inspect(engine).has_table(UserKey.__tablename__):
        return

    from . import provisioning

    with OrmSession(engine) as db:
        keys = list(db.scalars(select(UserKey).where(UserKey.address.is_not(None))))
        taken: dict[int, list[str]] = {}
        for key in keys:
            taken.setdefault(key.server_id, []).append(key.address)

        seen: set[tuple[int, str]] = set()
        moved = 0
        # Живой и самый поздний ключ идёт первым — он и остаётся на адресе.
        for key in sorted(keys, key=lambda k: (k.revoked_at is None, k.id), reverse=True):
            mark = (key.server_id, key.address)
            if mark not in seen:
                seen.add(mark)
                continue
            try:
                address = provisioning.next_address(taken[key.server_id])
            except Exception as exc:  # свободных адресов не осталось
                log.error("ключ %s: адрес %s занят, переселить некуда: %s", key.id, key.address, exc)
                continue
            log.warning(
                "миграция: ключ %s делил адрес %s на сервере %s, переселён на %s",
                key.id,
                key.address,
                key.server_id,
                address,
            )
            taken[key.server_id].append(address)
            key.address = address
            key.config = ""
            key.revoked_at = utcnow()
            moved += 1

        if moved:
            db.commit()
            log.warning("миграция: %d ключей с чужим адресом отправлены на перевыпуск", moved)


# --- данные -------------------------------------------------------------------


def _backfill_plan_kopecks(db: OrmSession) -> None:
    """Копейки для тарифов, заведённых до появления оплаты на сайте."""
    changed = 0
    for plan in db.scalars(select(Plan).where(Plan.price_kopecks == 0)):
        rubles = float(plan.price or 0)
        if rubles <= 0:
            continue
        plan.price_kopecks = int(round(rubles * 100))
        changed += 1
    if changed:
        db.commit()
        log.info("миграция: копейки проставлены у %d тарифов", changed)


def _encrypt_legacy_passwords(db: OrmSession) -> None:
    """
    Переносит пароли из `password_hint` в `password_enc` и стирает исходник.

    До появления шифрования пароль лежал в базе открытым текстом. Оставить
    его там после обновления — значит сохранить ровно ту дыру, ради которой
    писался crypto.py.
    """
    from . import crypto

    stale = list(db.scalars(select(User).where(User.password_hint.isnot(None))))
    if not stale:
        return
    if not crypto.available():
        log.warning(
            "%d паролей лежат открытым текстом, но PANEL_SECRETS_KEY не задан — "
            "задайте ключ и перезапустите панель",
            len(stale),
        )
        return

    for user in stale:
        if user.password_enc is None:
            user.password_enc = crypto.encrypt(user.password_hint)
        user.password_hint = None
    db.commit()
    log.info("миграция: %d паролей зашифровано", len(stale))
