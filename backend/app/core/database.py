# ========================== #
# backend.app.core.database
# ========================== #

"""
Asynchronous PostgreSQL infrastructure for the Weave CBT runtime.

PostgreSQL is the durable source of truth for:

- questions;
- examinations;
- candidates;
- attempts;
- candidate answers;
- examination results;
- synchronization state;
- local authentication/session records.

Architectural rules:

- all database I/O is asynchronous;
- SQLAlchemy uses asyncpg;
- application services control transaction boundaries;
- FastAPI dependencies do not automatically commit;
- database connectivity is required for API startup;
- fresh schemas are created and existing schemas validated at startup;
- Redis and process memory must never replace PostgreSQL
  for durable examination state.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, TypeAlias
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.settings import settings

# ========================== #
# DATABASE CONSTRAINT NAMES
# ========================== #

CONSTRAINT_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": ("fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"),
    "pk": "pk_%(table_name)s",
}


# ========================== #
# SQLALCHEMY METADATA
# ========================== #

metadata = MetaData(naming_convention=CONSTRAINT_NAMING_CONVENTION)


# ========================== #
# SQLALCHEMY BASE
# ========================== #


def _utc_now() -> datetime:
    """Return an aware UTC timestamp for ORM-managed audit fields.

    Using a Python value for ORM INSERT/UPDATE timestamps keeps those attributes
    resident after flush/commit. A SQL expression such as ``onupdate=func.now()``
    can leave the generated value expired; synchronous response serialization on
    an AsyncSession may then attempt implicit I/O and turn a successful mutation
    into a 500 response. PostgreSQL defaults remain as a database-side fallback.
    """

    return datetime.now(UTC)


class TimestampMixin:
    """
    Track when a local projection row was created and last updated.

    These timestamps describe the local CBT copy, not the original
    creation/update timestamp in Weave.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
        onupdate=_utc_now,
    )


class UUIDMixin:
    """Provide a UUID primary key for local CBT records"""

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Base(
    AsyncAttrs,
    TimestampMixin,
    UUIDMixin,
    DeclarativeBase,
):
    """
    Base class for all local CBT SQLAlchemy models.

    AsyncAttrs allows ORM relationships or attributes that require
    database I/O to be awaited explicitly when necessary.
    """

    metadata = metadata


# ========================== #
# ASYNC ENGINE
# ========================== #

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=(True if settings.ENVIRONMENT == "dev" else False),  # noqa: SIM210
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT_SECONDS,
    pool_recycle=settings.DATABASE_POOL_RECYCLE_SECONDS,
    pool_pre_ping=True,
)


# ========================== #
# SESSION FACTORY
# ========================== #

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


# ========================== #
# DATABASE HEALTH
# ========================== #


async def check_database_connection() -> None:
    """
    Verify that PostgreSQL is reachable.

    PostgreSQL is required for correct CBT operation.

    Failure here should prevent the FastAPI application from
    reporting itself as ready.
    """

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Unable to connect to the local CBT PostgreSQL database."
        ) from exc


# ========================== #
# FASTAPI SESSION DEPENDENCY
# ========================== #


async def get_database_session() -> AsyncIterator[AsyncSession]:
    """
    Provide one SQLAlchemy AsyncSession for a request.

    This dependency intentionally does not automatically commit.

    Transaction boundaries belong to application/domain services
    because those services know whether an operation must be atomic.

    If an exception escapes while a transaction is active,
    the session is rolled back.

    The async context manager closes the session automatically.
    """

    async with async_session_factory() as session:
        try:
            yield session

        except Exception:
            await session.rollback()
            raise


# ========================== #
# DATABASE SHUTDOWN
# ========================== #


async def dispose_database_engine() -> None:
    """
    Dispose this process's SQLAlchemy connection pool.

    Each FastAPI worker process owns its own engine and connection
    pool and should dispose it during graceful application shutdown.
    """

    await engine.dispose()


# ========================== #
# FASTAPI TYPE ALIASES
# ========================== #

DbSession: TypeAlias = Annotated[
    AsyncSession,
    Depends(get_database_session),
]
