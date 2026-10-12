"""Durable runtime infrastructure for crash recovery and realtime delivery."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

OUTBOX_EVENT_TYPE_MAX_LENGTH = 128
OUTBOX_AGGREGATE_TYPE_MAX_LENGTH = 64
OUTBOX_ERROR_MAX_LENGTH = 2048
RUNTIME_SHUTDOWN_REASON_MAX_LENGTH = 500


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class CBTRuntimeState(Base):
    """One durable record per CBT server boot."""

    __tablename__ = "cbt_runtime_states"

    runtime_id: Mapped[UUID] = mapped_column(
        nullable=False,
        unique=True,
        default=uuid4,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    shutdown_reason: Mapped[str | None] = mapped_column(
        String(RUNTIME_SHUTDOWN_REASON_MAX_LENGTH),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "last_heartbeat_at >= started_at",
            name="ck_cbt_runtime_states_heartbeat_after_start",
        ),
        CheckConstraint(
            "stopped_at IS NULL OR stopped_at >= started_at",
            name="ck_cbt_runtime_states_stop_after_start",
        ),
        CheckConstraint(
            "stopped_at IS NULL OR stopped_at >= last_heartbeat_at",
            name="ck_cbt_runtime_states_stop_after_heartbeat",
        ),
        CheckConstraint(
            "stopped_at IS NOT NULL OR shutdown_reason IS NULL",
            name="ck_cbt_runtime_states_shutdown_reason_requires_stop",
        ),
        Index(
            "ix_cbt_runtime_states_started_heartbeat",
            "started_at",
            "last_heartbeat_at",
        ),
    )


class RealtimeOutboxEvent(Base):
    """Transactional outbox row for significant committed lifecycle events."""

    __tablename__ = "realtime_outbox_events"

    aggregate_type: Mapped[str] = mapped_column(
        String(OUTBOX_AGGREGATE_TYPE_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    aggregate_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(OUTBOX_EVENT_TYPE_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    status: Mapped[OutboxEventStatus] = mapped_column(
        SQLEnum(
            OutboxEventStatus,
            name="outbox_event_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=OutboxEventStatus.PENDING,
        server_default=OutboxEventStatus.PENDING.value,
        index=True,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    publish_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    last_publish_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    claim_token: Mapped[UUID | None] = mapped_column(
        nullable=True,
        index=True,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "publish_attempts >= 0",
            name="ck_realtime_outbox_publish_attempts_nonnegative",
        ),
        CheckConstraint(
            "last_error IS NULL OR "
            f"char_length(last_error) <= {OUTBOX_ERROR_MAX_LENGTH}",
            name="ck_realtime_outbox_error_length",
        ),
        CheckConstraint(
            "(status = 'publishing' AND claim_token IS NOT NULL "
            "AND claimed_at IS NOT NULL) OR status <> 'publishing'",
            name="ck_realtime_outbox_publishing_requires_claim",
        ),
        CheckConstraint(
            "published_at IS NULL OR status = 'published'",
            name="ck_realtime_outbox_published_at_matches_status",
        ),
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_realtime_outbox_published_requires_timestamp",
        ),
        Index(
            "ix_realtime_outbox_dispatch",
            "status",
            "available_at",
        ),
        Index(
            "ix_realtime_outbox_aggregate",
            "aggregate_type",
            "aggregate_id",
        ),
        Index(
            "ix_realtime_outbox_stale_claim",
            "status",
            "claimed_at",
        ),
    )
