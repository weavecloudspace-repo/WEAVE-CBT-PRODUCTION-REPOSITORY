"""Create a fresh PostgreSQL schema, without modifying existing school data."""

from __future__ import annotations

import asyncio
import logging

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import configure_mappers

import app.model_registry  # noqa: F401
from alembic import command
from app.core.database import Base, engine
from app.core.migrations import migration_config, migration_head
from app.domains.exams.database_schema import (
    CONTRIBUTOR_TRIGGERS,
)

logger = logging.getLogger(__name__)
_BOOTSTRAP_LOCK_KEY = 873324110920260903


def _validate_existing_schema(connection: Connection) -> None:
    """Reject incompatible schemas instead of treating create_all as an upgrade."""
    inspector = inspect(connection)
    problems: list[str] = []
    for table in Base.metadata.sorted_tables:
        columns = {
            column["name"]: column
            for column in inspector.get_columns(table.name, schema="public")
        }
        for expected in table.columns:
            actual = columns.get(expected.name)
            if actual is None:
                problems.append(f"{table.name}.{expected.name} is missing")
            elif (
                str(actual["type"].compile(dialect=connection.dialect))
                != str(expected.type.compile(dialect=connection.dialect))
                or actual["nullable"] != expected.nullable
            ):
                problems.append(
                    f"{table.name}.{expected.name} has an incompatible type or nullability"
                )
        actual_pk = inspector.get_pk_constraint(table.name, schema="public")[
            "constrained_columns"
        ]
        if actual_pk != [column.name for column in table.primary_key.columns]:
            problems.append(f"{table.name} has an incompatible primary key")
        actual_indexes = {
            item["name"]: item
            for item in inspector.get_indexes(table.name, schema="public")
        }
        for index in table.indexes:
            actual = actual_indexes.get(index.name)
            simple_columns = all(isinstance(item, Column) for item in index.expressions)
            if (
                actual is None
                or bool(actual["unique"]) != bool(index.unique)
                or (
                    simple_columns
                    and actual["column_names"]
                    != [item.name for item in index.expressions]
                )
            ):
                problems.append(
                    f"{table.name} index {index.name} is missing or incompatible"
                )
        actual_checks = {
            item["name"]
            for item in inspector.get_check_constraints(table.name, schema="public")
        }
        actual_unique = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table.name, schema="public")
        }
        actual_fks = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
                item["options"].get("ondelete"),
            )
            for item in inspector.get_foreign_keys(table.name, schema="public")
        }
        for constraint in table.constraints:
            if (
                isinstance(constraint, CheckConstraint)
                and constraint.name not in actual_checks
            ):
                problems.append(f"{table.name} check {constraint.name} is missing")
            elif (
                isinstance(constraint, UniqueConstraint)
                and tuple(column.name for column in constraint.columns)
                not in actual_unique
            ):
                problems.append(
                    f"{table.name} unique constraint {constraint.name} is missing"
                )
            elif isinstance(constraint, ForeignKeyConstraint):
                signature = (
                    tuple(element.parent.name for element in constraint.elements),
                    constraint.elements[0].column.table.name,
                    tuple(element.column.name for element in constraint.elements),
                    constraint.ondelete,
                )
                if signature not in actual_fks:
                    problems.append(
                        f"{table.name} foreign key {constraint.name} is missing or incompatible"
                    )
    triggers = set(
        connection.execute(
            text(
                "SELECT c.relname, t.tgname FROM pg_catalog.pg_trigger t "
                "JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND NOT t.tgisinternal AND t.tgenabled <> 'D'"
            )
        ).tuples()
    )
    for required in CONTRIBUTOR_TRIGGERS:
        if required not in triggers:
            problems.append(
                f"{required[0]} trigger {required[1]} is missing or disabled"
            )
    if problems:
        raise RuntimeError(
            "The existing CBT database schema is incompatible. Refusing automatic repair. "
            "Back up its data and apply an explicit schema upgrade before restarting. "
            + "; ".join(problems[:12])
        )


async def bootstrap_database(database_engine: AsyncEngine = engine) -> bool:
    """Apply Alembic under a transaction lock; never adopt an unversioned schema."""
    configure_mappers()
    head = migration_head()
    expected_tables = {table.name for table in Base.metadata.tables.values()}
    if not expected_tables:
        raise RuntimeError("The model registry is empty; refusing database bootstrap.")
    async with database_engine.begin() as connection:
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY}
        )
        # Models and trigger SQL consistently use the public schema.
        await connection.execute(text("SET LOCAL search_path TO public"))
        result = await connection.execute(
            text(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
            )
        )
        existing_tables = set(result.scalars())
        if existing_tables:
            if not (existing_tables - {"alembic_version"}):
                raise RuntimeError(
                    "The CBT database has a migration marker without application tables. "
                    "Refusing automatic repair or stamping."
                )
            current = await connection.run_sync(
                lambda sync: MigrationContext.configure(sync).get_current_heads()
            )
            scripts = ScriptDirectory.from_config(migration_config())
            known = {revision.revision for revision in scripts.walk_revisions()}
            if len(current) != 1 or current[0] not in known:
                raise RuntimeError(
                    "The CBT database requires an Alembic upgrade or explicit adoption. "
                    "Refusing automatic repair or stamping. Back up the database and "
                    "run `alembic upgrade head` from backend/ for a versioned database. "
                    f"Current revisions: {current}; expected: {head}."
                )

        def upgrade(sync: Connection) -> None:
            config = migration_config()
            config.attributes["connection"] = sync
            command.upgrade(config, "head")

        await connection.run_sync(upgrade)
        tables = set(
            (
                await connection.execute(
                    text(
                        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
                    )
                )
            ).scalars()
        )
        missing = expected_tables - tables
        if missing:
            raise RuntimeError(
                "The CBT database is partially initialized. Refusing automatic repair. "
                "Missing tables: " + ", ".join(sorted(missing))
            )
        await connection.run_sync(_validate_existing_schema)
        logger.info("CBT database migrated and validated at revision %s", head)
        return not existing_tables


async def _main() -> None:
    try:
        await bootstrap_database()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
