"""Подключение к базе и первичная настройка."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import GB, Admin, Base, Plan
from .security import hash_password

# Тарифы «из коробки»: панель без единого тарифа не даёт завести человека,
# а придумывать их в первый день никто не хочет.
DEFAULT_PLANS = [
    # code, название, цена, дней, лимит трафика (None — безлимит), порядок
    ("trial", "Пробный", 0, 7, 5 * GB, 0),
    ("basic", "Базовый", 199, 30, 100 * GB, 1),
    ("pro", "Про", 349, 30, None, 2),
    ("year", "Годовой", 2990, 365, None, 3),
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
    """Создаёт таблицы, первого администратора и базовые тарифы."""
    Base.metadata.create_all(engine)

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

        # Тарифы досоздаём по коду, а не «если таблица пуста»: удалённый
        # администратором тариф не должен возвращаться, а новый в обновлении —
        # должен появиться.
        if db.scalar(select(Plan).limit(1)) is None:
            for code, name, price, days, limit, order in DEFAULT_PLANS:
                db.add(
                    Plan(
                        code=code,
                        name=name,
                        price=price,
                        currency=config.currency,
                        period_days=days,
                        traffic_limit_bytes=limit,
                        sort_order=order,
                    )
                )
            db.commit()
