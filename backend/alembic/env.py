"""Async PostgreSQL migrations using the application's model registry."""

import asyncio

import app.model_registry  # noqa: F401
from alembic import context
from app.core.database import Base
from app.core.migrations import include_schema_object
from app.core.settings import settings
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine


def run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_schema_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_schema_object,
    )
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    run_migrations(context.config.attributes["connection"])
else:
    asyncio.run(run_online())
