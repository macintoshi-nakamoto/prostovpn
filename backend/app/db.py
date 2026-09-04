from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from . import migrations
from .config import settings
from .models import Admin, Base, Plan
from .security import hash_password

GB = 1024**3

# (код, название, цена в копейках, дней, трафик, узлов, устройств, публичный,
# подпись). Устройства с 04.09.2026: пробный — одно и 15 ГБ, чтобы пробу не
# раздавали на всю семью; платные — по сроку, чем дольше, тем больше.
DEFAULT_PLANS = [
    ("trial", "Пробный", 0, 2, 15 * GB, 3, 1, True, "Два дня, 15 ГБ, одно устройство"),
    ("daily", "Посуточный", 1_000, 1, None, 3, 1, True, "Сколько нужно дней — столько и берите"),
    ("basic", "Базовый", 19_900, 30, None, 3, 3, True, None),
    ("3months", "Сезонная", 49_900, 90, None, 3, 5, True, None),
    ("preyear", "Полугодовая", 89_900, 180, None, 3, 7, True, None),
    ("year", "Годовая", 149_900, 365, None, 3, 10, True, None),
]

_url = settings().database_url
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_engine(_url, echo=False, future=True, connect_args=_connect_args)

if _url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[OrmSession]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    migrations.run(engine)

    config = settings()
    with SessionLocal() as db:
        exists = db.scalar(select(Admin).limit(1))
        if exists is None:
            db.add(
                Admin(
                    login=config.admin_login,
                    password_hash=hash_password(config.admin_password),
                )
            )
            db.commit()

        if db.scalar(select(Plan).limit(1)) is None:
            for order, row in enumerate(DEFAULT_PLANS):
                code, name, kopecks, days, traffic, servers, devices, public, tagline = row
                plan = Plan(
                    code=code,
                    name=name,
                    currency=config.currency,
                    period_days=days,
                    traffic_limit_bytes=traffic,
                    server_limit=servers,
                    device_limit=devices,
                    is_public=public,
                    tagline=tagline,
                    sort_order=order,
                )
                plan.set_price(kopecks)
                db.add(plan)
            db.commit()

        migrations.backfill(db)
