"""SQLAlchemy 2.0 base, engine, and session factory."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _configure_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
    """Enable WAL mode and foreign keys for SQLite connections."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(url: str, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for SQLite or Postgres."""
    is_sqlite = url.startswith("sqlite")
    connect_args: dict[str, Any] = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(url, echo=echo, connect_args=connect_args, future=True)
    if is_sqlite:
        event.listen(engine, "connect", _configure_sqlite_pragma)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to an engine."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all tables in the target database."""
    Base.metadata.create_all(bind=engine)
