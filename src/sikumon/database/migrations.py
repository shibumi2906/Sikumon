"""Small deterministic schema-version migration entry point."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from sikumon.config.constants import CURRENT_SCHEMA_VERSION
from sikumon.database.orm_models import Base, SchemaVersionORM

Migration = Callable[[Engine], None]


@dataclass(frozen=True, slots=True)
class MigrationStep:
    from_version: int
    to_version: int
    upgrade: Migration


def _create_initial_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


MIGRATIONS: tuple[MigrationStep, ...] = (
    MigrationStep(from_version=0, to_version=1, upgrade=_create_initial_schema),
)


def plan_migrations(
    current_version: int,
    target_version: int,
    migrations: tuple[MigrationStep, ...] = MIGRATIONS,
) -> tuple[MigrationStep, ...]:
    """Return one unbroken, deterministic upgrade chain or fail explicitly."""

    if current_version > target_version:
        raise RuntimeError(
            f"Database schema {current_version} is newer than supported schema {target_version}"
        )
    by_source = {step.from_version: step for step in migrations}
    planned: list[MigrationStep] = []
    version = current_version
    while version < target_version:
        step = by_source.get(version)
        if step is None or step.to_version != version + 1:
            raise RuntimeError(f"Missing migration from schema version {version} to {version + 1}")
        planned.append(step)
        version = step.to_version
    return tuple(planned)


def get_schema_version(engine: Engine) -> int:
    if not inspect(engine).has_table(SchemaVersionORM.__tablename__):
        return 0
    with Session(engine) as session:
        version = session.scalar(select(SchemaVersionORM.version).where(SchemaVersionORM.singleton == 1))
        return int(version or 0)


def apply_migrations(engine: Engine, logger: logging.Logger | None = None) -> int:
    version = get_schema_version(engine)
    for step in plan_migrations(version, CURRENT_SCHEMA_VERSION):
        if logger:
            logger.info(
                "Applying database schema migration %s -> %s",
                step.from_version,
                step.to_version,
            )
        step.upgrade(engine)
        with Session(engine) as session, session.begin():
            row = session.get(SchemaVersionORM, 1)
            if row is None:
                session.add(SchemaVersionORM(singleton=1, version=step.to_version))
            else:
                row.version = step.to_version
    if logger:
        logger.info("Database schema version %s", CURRENT_SCHEMA_VERSION)
    return CURRENT_SCHEMA_VERSION
