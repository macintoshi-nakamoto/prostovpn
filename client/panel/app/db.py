"""Подключение к базе и первичная настройка."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import Admin, Base
from .security import hash_password

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
    """Создаёт таблицы и первого администратора, если админов ещё нет."""
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
