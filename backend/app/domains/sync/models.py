"""Durable local synchronization checkpoint state."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.integrations.weave.schemas import SYNC_SCHEMA_VERSION

SYNC_SCOPE_MAX_LENGTH = 64
SYNC_ERROR_MAX_LENGTH = 1024


class SyncState(Base):
    """One durable cursor/checkpoint for a Cloud -> CBT synchronization scope."""

    __tablename__ = "sync_states"

    scope: Mapped[str] = mapped_column(
        String(SYNC_SCOPE_MAX_LENGTH), nullable=False, unique=True
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=SYNC_SCHEMA_VERSION,
        server_default=text(str(SYNC_SCHEMA_VERSION)),
    )
    cursor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    bootstrap_snapshot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    bootstrap_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("cursor >= 0", name="ck_sync_states_cursor_nonnegative"),
        CheckConstraint(
            "schema_version >= 1", name="ck_sync_states_schema_version_positive"
        ),
        CheckConstraint(
            f"last_error IS NULL OR char_length(last_error) <= {SYNC_ERROR_MAX_LENGTH}",
            name="ck_sync_states_error_length",
        ),
    )
