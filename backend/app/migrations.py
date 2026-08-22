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
    # Единственное исключение из правила «не менять то, что уже есть»: см.
    # _widen_user_keys_unique. Ограничение снимается до всего остального,
    # иначе выдача ключей второму устройству падает с IntegrityError.
    _widen_user_keys_unique(engine)
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
    _encrypt_legacy_emails(db)
    _encrypt_key_private_keys(db)
    _measure_published_releases(db)


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


def _widen_user_keys_unique(engine: Engine) -> None:
    """
    Снимает с `user_keys` старую уникальность по паре (user_id, server_id).

    Ровно то, чего этот механизм обычно не делает, — и делается один раз, с
    причиной. Пока пара была уникальной, у человека физически не могло быть
    двух ключей на одном сервере, то есть двух пиров, то есть отключить одно
    устройство, не отключив остальные, было нечем. Теперь уникальность — по
    тройке с `device_id`, и старое ограничение обязано уйти, иначе выдача
    ключа второму устройству падает на вставке.

    В SQLite ограничение записано в самом CREATE TABLE и отдельной командой
    не снимается — таблицу приходится пересобирать. Данные при этом никуда
    не деваются: сначала полная копия, потом чистая таблица из моделей,
    потом обратная заливка, и всё это в одной транзакции.
    """
    inspector = inspect(engine)
    table = UserKey.__table__
    if not inspector.has_table(table.name):
        return

    stale = [
        constraint
        for constraint in inspector.get_unique_constraints(table.name)
        if set(constraint["column_names"]) == {"user_id", "server_id"}
    ]
    if not stale:
        return

    if engine.dialect.name != "sqlite":
        with engine.begin() as conn:
            for constraint in stale:
                conn.execute(
                    text(f'ALTER TABLE {table.name} DROP CONSTRAINT "{constraint["name"]}"')
                )
        log.warning("миграция: снята уникальность (user_id, server_id) с %s", table.name)
        return

    present = {column["name"] for column in inspector.get_columns(table.name)}
    columns = [column.name for column in table.columns if column.name in present]
    column_list = ", ".join(f'"{name}"' for name in columns)
    # `device_id` мог приехать в старую таблицу отдельной колонкой и остаться
    # пустым: NOT NULL к непустой таблице не добавляют. В новой схеме он
    # обязателен, поэтому пустоту превращаем в «ключ учётки» на переливке.
    select_list = ", ".join(
        'COALESCE("device_id", \'\')' if name == "device_id" else f'"{name}"' for name in columns
    )

    with engine.begin() as conn:
        # Копия без индексов и ограничений: она нужна ровно на время
        # пересборки и переживёт удаление исходной таблицы вместе с её
        # индексами, имена которых иначе столкнулись бы с новыми.
        conn.execute(text(f"CREATE TABLE _user_keys_rebuild AS SELECT * FROM {table.name}"))
        conn.execute(text(f"DROP TABLE {table.name}"))
        table.create(conn)
        conn.execute(
            text(
                f"INSERT INTO {table.name} ({column_list}) "
                f"SELECT {select_list} FROM _user_keys_rebuild"
            )
        )
        moved = conn.execute(text(f"SELECT count(*) FROM {table.name}")).scalar_one()
        conn.execute(text("DROP TABLE _user_keys_rebuild"))

    log.warning(
        "миграция: %s пересобрана под ключи на устройство, перенесено строк: %d",
        table.name,
        moved,
    )


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


def _encrypt_legacy_emails(db: OrmSession) -> None:
    """
    Переносит почту из открытого `email` в шифротекст и слепой индекс.

    Та же судьба, что у паролей: адреса лежали открытым текстом, а это
    ровно то, что уходит первым при утечке базы. После переноса открытое
    поле пустеет; поиск работает по HMAC-индексу, показ — по расшифровке.

    Без ключа шифрования ничего не трогаем, но индекс всё равно считаем:
    он нужен поиску при повторной покупке, а не только шифрованию.
    """
    from . import crypto
    from .models import normalize_email

    stale = list(db.scalars(select(User).where(User.email.isnot(None))))
    if not stale:
        return

    if not crypto.available():
        log.warning(
            "%d адресов почты лежат открытым текстом, но PANEL_SECRETS_KEY не задан — "
            "задайте ключ и перезапустите панель",
            len(stale),
        )
        for user in stale:
            if user.email_hash is None:
                user.email_hash = crypto.blind_index(normalize_email(user.email))
        db.commit()
        return

    for user in stale:
        user.set_email(user.email)
    db.commit()
    log.info("миграция: %d адресов почты зашифровано", len(stale))


def _encrypt_key_private_keys(db: OrmSession) -> None:
    """
    Шифрует приватные ключи клиентов из текста конфига в `private_key_enc`.

    Первый из двух шагов перехода на шифрование at-rest: открытый текст
    `PrivateKey = ...` внутри `config` НЕ трогаем — он остаётся аварийной
    копией на случай, если сборка из шифра где-то ошиблась. Вычистка
    плейнтекста — отдельный осознанный шаг (tools/strip_plaintext_keys.py),
    только после проверки, что все пути читают ключ из шифра.

    Без ключа шифрования ничего не делаем и не падаем: приватники остаются как
    были, читатели берут их из текста через provisioning.private_key_for.
    """
    from . import crypto, provisioning

    stale = list(
        db.scalars(
            select(UserKey).where(
                UserKey.private_key_enc.is_(None), UserKey.config.isnot(None)
            )
        )
    )
    if not stale:
        return

    if not crypto.available():
        log.warning(
            "%d приватных ключей лежат открытым текстом, но PANEL_SECRETS_KEY не задан — "
            "задайте ключ и перезапустите панель",
            len(stale),
        )
        return

    changed = 0
    for key in stale:
        pk = provisioning.interface_params(key.config or "").get("PrivateKey", "")
        if not pk or pk == provisioning.ENCRYPTED_PLACEHOLDER:
            continue
        key.private_key_enc = crypto.encrypt(pk)
        changed += 1
    if changed:
        db.commit()
        log.info(
            "миграция: %d приватных ключей зашифровано "
            "(открытый текст пока оставлен как аварийная копия)",
            changed,
        )


def _measure_published_releases(db: OrmSession) -> None:
    """
    Досчитывает sha256 у уже опубликованных версий.

    Раньше сумму вписывали руками и потому не вписывали вовсе — а приложение
    без неё отказывается ставить обновление, и кнопка «Обновить» падала
    ошибкой у всех сразу. Считаем на старте: файл обычно лежит на этом же
    сервере, чтение занимает доли секунды. Не вышло — версия остаётся как
    была, а причина уходит в журнал: старт панели этим ронять нечего.
    """
    from .config import settings
    from .models import AppRelease
    from .services import releases

    stale = list(
        db.scalars(
            select(AppRelease).where(AppRelease.sha256.is_(None), AppRelease.is_active.is_(True))
        )
    )
    if not stale:
        return

    fixed = 0
    for release in stale:
        # Только файл с диска: ходить по сети на старте нельзя — недоступная
        # ссылка задержала бы запуск панели на таймаут, и не один раз.
        if releases.local_installer(release.url) is None:
            log.warning(
                "версия %s %s без контрольной суммы: установщика нет в %s — "
                "приложение откажется ставить это обновление",
                release.platform,
                release.version,
                settings().downloads_dir or "(каталог установщиков не задан)",
            )
            continue
        try:
            checksum, size = releases.measure(release.url)
        except Exception as exc:  # noqa: BLE001 - причина уходит в журнал, старт не рвём
            log.warning(
                "версия %s %s без контрольной суммы, обновление по ней не поставится: %s",
                release.platform,
                release.version,
                exc,
            )
            continue
        release.sha256 = checksum
        if not release.size_bytes:
            release.size_bytes = size
        fixed += 1

    if fixed:
        db.commit()
        log.info("миграция: контрольная сумма посчитана у %d версий приложения", fixed)
