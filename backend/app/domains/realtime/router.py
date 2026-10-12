# =========================== #
#       runtime/models.py     #
# =========================== #

"""
Durable runtime infrastructure models for the local Weave CBT server.

This domain owns operational state required for:

- whole-server crash/outage recovery;
- transactional realtime event delivery.

PostgreSQL remains authoritative.

Redis may be used later for realtime delivery, presence, Pub/Sub and
coordination, but Redis is never the durable source of truth for these
records.
"""

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


# ========================== #
# ENUMS
# ========================== #


class OutboxEventStatus(StrEnum):
    """
    Delivery state of a durable realtime outbox event.

    PENDING
        Event has been committed with the business transaction and
        is waiting to be published.

    PUBLISHING
        A dispatcher has claimed the event for delivery.

    PUBLISHED
        The event has successfully been handed to the realtime
        transport layer.

    FAILED
        The latest publication attempt failed. The event remains
        available for retry according to `available_at`.
    """

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


# ========================== #
# CBT RUNTIME STATE
# ========================== #


class CBTRuntimeState(Base):
    """
    Durable record of one local CBT runtime boot.

    A NEW row is created whenever the CBT server starts.

    Do not reuse the previous boot's row.

    Example:

        boot A
            started_at         = 09:00:00
            last_heartbeat_at  = 10:31:05
            stopped_at         = NULL

        power failure at ~10:31

        boot B starts at 10:52

    On boot B, recovery logic can inspect boot A and determine:

        - boot A never shut down gracefully;
        - its last durable heartbeat was 10:31:05;
        - any IN_PROGRESS attempts may need outage recovery from
          approximately that boundary.

    Only ONE designated runtime coordinator should update this heartbeat.

    Individual FastAPI workers must not each create independent runtime
    heartbeat rows.
    """

    __tablename__ = "cbt_runtime_states"

    # Unique identifier for one complete server boot.
    #
    # This is separate from Base.id because it represents the logical
    # runtime instance and may safely be included in logs/events without
    # coupling operational semantics to the database primary key.
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

    # Durable whole-runtime heartbeat.
    #
    # A coordinator may update this approximately every five seconds.
    #
    # This is NOT the same thing as candidate/WebSocket presence.
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Populated only during a graceful shutdown.
    #
    # If the machine loses power, this remains NULL.
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


# ========================== #
# REALTIME OUTBOX EVENT
# ========================== #


class RealtimeOutboxEvent(Base):
    """
    Durable transactional event waiting to be published to the realtime
    transport layer.

    This implements the transactional outbox pattern.

    Example:

        Admin activates exam.

        BEGIN

            UPDATE exams
            SET status = 'active'

            INSERT realtime_outbox_events
                event_type = 'exam.activated'

        COMMIT

    The exam becoming ACTIVE and the event being created therefore happen
    in the SAME PostgreSQL transaction.

    A dispatcher later publishes the event through Redis/WebSockets.

    This avoids:

        database commit succeeds
                ↓
        process crashes
                ↓
        realtime event disappears

    because the unpublished outbox row remains safely in PostgreSQL.

    This table should contain significant state-change notifications,
    not high-frequency candidate answer traffic or presence heartbeats.

    Examples:

        exam.activated
        exam.suspended
        exam.resumed
        exam.closed

        attempt.started
        attempt.interrupted
        attempt.resumed
        attempt.submitted
        attempt.terminated

        roster.ready
        roster.failed

        result.calculated
        result.synced
    """

    __tablename__ = "realtime_outbox_events"

    # Domain object that produced the event.
    #
    # Examples:
    #
    # aggregate_type = "exam"
    # aggregate_id   = Exam.id
    #
    # aggregate_type = "attempt"
    # aggregate_id   = ExamAttempt.id
    aggregate_type: Mapped[str] = mapped_column(
        String(OUTBOX_AGGREGATE_TYPE_MAX_LENGTH),
        nullable=False,
        index=True,
    )

    aggregate_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )

    # Examples:
    #
    # exam.activated
    # attempt.submitted
    # roster.ready
    event_type: Mapped[str] = mapped_column(
        String(OUTBOX_EVENT_TYPE_MAX_LENGTH),
        nullable=False,
        index=True,
    )

    # Small transport payload.
    #
    # Do NOT place:
    #
    # - plaintext CBT PINs;
    # - credential verifiers;
    # - complete question papers;
    # - full candidate answer state
    #
    # in realtime outbox payloads.
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

    # Earliest time this event should be considered for delivery.
    #
    # Failed events can move this into the future to implement retry
    # backoff without creating separate scheduled jobs per event.
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

    # Lease information used when one dispatcher claims an event.
    #
    # This makes multiple dispatcher processes safe:
    #
    # dispatcher A claims event
    #     ↓
    # claim_token = UUID
    # claimed_at = now
    # status = PUBLISHING
    #
    # If dispatcher A crashes, a stale lease can later be reclaimed.
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
            "("
            "status = 'publishing' "
            "AND claim_token IS NOT NULL "
            "AND claimed_at IS NOT NULL"
            ") OR ("
            "status <> 'publishing'"
            ")",
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
