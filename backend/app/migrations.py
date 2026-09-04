from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, select, text, update
from sqlalchemy.orm import Session as OrmSession

from .models import Base, Plan, Referral, User, UserKey, utcnow

log = logging.getLogger("panel.migrations")


def run(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    _widen_user_keys_unique(engine)
    _relax_referral_telegram(engine)
    _dedupe_key_addresses(engine)
    _create_missing_indexes(engine)


def backfill(db: OrmSession) -> None:
    _backfill_plan_kopecks(db)
    _encrypt_legacy_passwords(db)
    _encrypt_legacy_emails(db)
    _encrypt_key_private_keys(db)
    _strip_plaintext_private_keys(db)
    _encrypt_server_ssh_secrets(db)
    _seed_node_endpoints(db)
    _measure_published_releases(db)


def _literal_default(column, dialect_name: str) -> str | None:
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, bool):
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
            except Exception as exc:
                log.error("индекс %s не создан: %s", index.name, exc)


def _widen_user_keys_unique(engine: Engine) -> None:
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
    select_list = ", ".join(
        'COALESCE("device_id", \'\')' if name == "device_id" else f'"{name}"' for name in columns
    )

    with engine.begin() as conn:
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


def _relax_referral_telegram(engine: Engine) -> None:
    inspector = inspect(engine)
    table = Referral.__table__
    if not inspector.has_table(table.name):
        return

    strict = [
        column["name"]
        for column in inspector.get_columns(table.name)
        if column["name"] in {"inviter_telegram_id", "invited_telegram_id"}
        and not column["nullable"]
    ]
    if not strict:
        return

    if engine.dialect.name != "sqlite":
        with engine.begin() as conn:
            for name in strict:
                conn.execute(
                    text(f'ALTER TABLE {table.name} ALTER COLUMN "{name}" DROP NOT NULL')
                )
        log.warning("миграция: телеграм в %s стал необязательным", table.name)
        return

    present = {column["name"] for column in inspector.get_columns(table.name)}
    columns = [column.name for column in table.columns if column.name in present]
    column_list = ", ".join(f'"{name}"' for name in columns)

    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE _referrals_rebuild AS SELECT * FROM {table.name}"))
        conn.execute(text(f"DROP TABLE {table.name}"))
        table.create(conn)
        conn.execute(
            text(
                f"INSERT INTO {table.name} ({column_list}) "
                f"SELECT {column_list} FROM _referrals_rebuild"
            )
        )
        moved = conn.execute(text(f"SELECT count(*) FROM {table.name}")).scalar_one()
        conn.execute(text("DROP TABLE _referrals_rebuild"))

    log.warning(
        "миграция: %s пересобрана под приглашения с сайта, перенесено строк: %d",
        table.name,
        moved,
    )


def _dedupe_key_addresses(engine: Engine) -> None:
    if not inspect(engine).has_table(UserKey.__tablename__):
        return

    from . import provisioning

    def _subnet_of(address: str | None) -> str:
        import ipaddress

        try:
            host = ipaddress.ip_address((address or "").split("/")[0])
        except ValueError:
            return "10.8.1.0/24"
        return str(ipaddress.ip_network(f"{host}/24", strict=False))

    with OrmSession(engine) as db:
        keys = list(db.scalars(select(UserKey).where(UserKey.address.is_not(None))))
        taken: dict[int, list[str]] = {}
        for key in keys:
            taken.setdefault(key.server_id, []).append(key.address)

        seen: set[tuple[int, str]] = set()
        moved = 0
        for key in sorted(keys, key=lambda k: (k.revoked_at is None, k.id), reverse=True):
            mark = (key.server_id, key.address)
            if mark not in seen:
                seen.add(mark)
                continue
            try:
                address = provisioning.next_address(
                    taken[key.server_id], subnet=_subnet_of(key.address)
                )
            except Exception as exc:
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


def _backfill_plan_kopecks(db: OrmSession) -> None:
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


def _strip_plaintext_private_keys(db: OrmSession) -> None:
    """
    Убирает «аварийную копию» приватного ключа из user_keys.config: у кого
    ключ уже под шифром, открытый текст рядом — лишний. Утечка базы без
    PANEL_SECRETS_KEY теперь не отдаёт ключи клиентов.
    """
    from . import crypto, provisioning

    if not crypto.available():
        return
    rows = list(
        db.scalars(
            select(UserKey).where(UserKey.private_key_enc.isnot(None), UserKey.config.isnot(None))
        )
    )
    changed = 0
    for key in rows:
        current = provisioning.interface_params(key.config or "").get("PrivateKey", "")
        if not current or current == provisioning.ENCRYPTED_PLACEHOLDER:
            continue
        # Шифротекст обязан читаться — иначе оставляем как есть, чтобы не
        # потерять единственную копию.
        try:
            if crypto.decrypt(key.private_key_enc) != current:
                key.private_key_enc = crypto.encrypt(current)
        except Exception:
            continue
        key.config = provisioning.with_private_key(key.config, provisioning.ENCRYPTED_PLACEHOLDER)
        changed += 1
    if changed:
        db.commit()
        log.info("миграция: открытый текст приватных ключей убран из %d записей", changed)


def _encrypt_server_ssh_secrets(db: OrmSession) -> None:
    """Ключи и пароли SSH узлов — под шифр. Это root на всём парке, и лежать
    открытым текстом рядом с остальными (уже зашифрованными) секретами им
    нечего."""
    from . import crypto
    from .models import Server

    if not crypto.available():
        return
    done = 0
    for server in db.scalars(select(Server)):
        for field in ("ssh_key", "ssh_password"):
            value = getattr(server, field)
            if value and not crypto.is_encrypted(value):
                setattr(server, field, crypto.encrypt(value))
                done += 1
    if done:
        db.commit()
        log.info("секреты SSH узлов зашифрованы: %d", done)


def _seed_node_endpoints(db: OrmSession) -> None:
    from . import obfuscation as obf
    from . import provisioning
    from .models import EndpointKind, EndpointState, NodeEndpoint, Provisioning, Server

    pending = [
        server
        for server in db.scalars(
            select(Server).where(
                Server.endpoints_seeded.is_(False),
                Server.provisioning == Provisioning.SSH,
            )
        )
        if server.keys and not server.endpoints
    ]
    if not pending:
        return

    seeded = 0
    for server in pending:
        if not server.awg_template:
            log.warning(
                "узел «%s»: нет шаблона конфига, точка входа awg0 не заведена — "
                "ключи на нём останутся без привязки",
                server.name,
            )
            continue
        try:
            values = obf.from_config_text(server.awg_template, strict=False)
        except obf.InvalidObfuscation as exc:
            log.warning("узел «%s»: набор обфускации не прочитан (%s)", server.name, exc)
            continue

        interface = provisioning.interface_params(server.awg_template)
        _, peer = provisioning.config_sections(server.awg_template)
        endpoint = NodeEndpoint(
            server_id=server.id,
            kind=EndpointKind.AWG,
            transport="udp",
            handle=provisioning.INTERFACE,
            listen_port=server.port,
            alt_ports=server.alt_ports or "",
            subnet="10.8.1.0/24",
            params={
                **values.as_dict(),
                "dns": interface.get("DNS", "1.1.1.1, 1.0.0.1"),
                "mtu": int(interface.get("MTU", "1280") or 1280),
                "allowed_ips": peer.get("AllowedIPs", "0.0.0.0/0, ::/0"),
                "keepalive": int(peer.get("PersistentKeepalive", "25") or 25),
                "server_public_key": peer.get("PublicKey", ""),
            },
            priority=0,
            state=EndpointState.ACTIVE,
            note="заведена автоматически из исторического конфига узла",
        )
        db.add(endpoint)
        db.flush()

        db.execute(
            update(UserKey)
            .where(UserKey.server_id == server.id, UserKey.endpoint_id.is_(None))
            .values(endpoint_id=endpoint.id)
        )
        server.endpoints_seeded = True
        seeded += 1

    if seeded:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("миграция точек входа не удалась, работаем без них: %s", exc)
            return
        log.info("миграция: заведено точек входа awg0 на узлах: %d", seeded)


def _measure_published_releases(db: OrmSession) -> None:
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
        except Exception as exc:
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
