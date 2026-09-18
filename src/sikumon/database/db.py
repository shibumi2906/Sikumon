"""Engine and session creation."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def create_sqlite_engine(database_path: Path, logger: logging.Logger | None = None) -> Engine:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    if logger:
        logger.info("Initializing SQLite database at %s", database_path)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

