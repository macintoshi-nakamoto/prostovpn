"""Подключение к базе и первичная настройка."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from . import migrations
from .config import settings
from .models import Admin, Base, Plan
from .security import hash_password

# Тарифы «из коробки»: панель без единого тарифа не даёт завести человека,
# а придумывать их в первый день никто не хочет. Цены здесь — стартовые:
# дальше они правятся в разделе «Тарифы», и сайт берёт их оттуда, а не из
# кода. Ставить цену в шаблон страницы нельзя — она разойдётся с той, по
# которой выставлен счёт.
DEFAULT_PLANS = [
    # code, название, копейки, дней, серверов, устройств, публичный, подпись
    ("trial", "Пробный", 0, 7, 3, 1, False, "Неделя для проверки"),
    ("basic", "Базовый", 30_000, 30, 3, 3, True, "Три страны, три устройства"),
    ("plus", "На три месяца", 80_000, 90, 3, 3, True, "Те же условия, дешевле в месяц"),
    ("max", "На год", 270_000, 365, 3, 5, True, "Максимальная выгода и пять устройств"),
]

_url = settings().database_url
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_engine(_url, echo=False, future=True, connect_args=_connect_args)

if _url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - вызывается драйвером
        cursor = dbapi_connection.cursor()
        # Без этого SQLite игнорирует ON DELETE CASCADE
        cursor.execute("PRAGMA foreign_keys=ON")
        # Иначе панель и фоновые задачи блокируют друг друга на записи
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
    """Создаёт таблицы, доводит схему до актуальной, заводит админа и тарифы."""
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

        # Тарифы заводим только в пустую базу: удалённый администратором тариф
        # не должен возвращаться при каждом перезапуске.
        if db.scalar(select(Plan).limit(1)) is None:
            for order, row in enumerate(DEFAULT_PLANS):
                code, name, kopecks, days, servers, devices, public, tagline = row
                plan = Plan(
                    code=code,
                    name=name,
                    currency=config.currency,
                    period_days=days,
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
