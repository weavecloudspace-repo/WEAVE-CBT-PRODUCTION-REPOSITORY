"""Durable orchestration state for examination completion and result review."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

EXECUTION_ERROR_MAX_LENGTH = 2048
RESULT_DECISION_REASON_MAX_LENGTH = 1000


class ExamExecutionOperation(StrEnum):
    """Long-running terminal operation currently owned by a worker."""

    CLOSING = "closing"
    CANCELLING = "cancelling"


class ExamOperationSource(StrEnum):
    """Who initiated a terminal exam operation."""

    ADMIN = "admin"
    AUTOMATIC = "automatic"


class ExamResultDisposition(StrEnum):
    """School decision controlling whether local CBT scores may leave the node."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    VOIDED = "voided"


class ExamExecutionControl(Base):
    """One durable execution/review control row per examination.

    Exam.status remains the execution state machine. This row keeps the durable
    cutoff used by asynchronous finalization and the independent academic
    decision that gates result synchronization.
    """

    __tablename__ = "exam_execution_controls"

    exam_id: Mapped[UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    operation: Mapped[ExamExecutionOperation | None] = mapped_column(
        SQLEnum(
            ExamExecutionOperation,
            name="exam_execution_operation",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=True,
        index=True,
    )
    operation_source: Mapped[ExamOperationSource | None] = mapped_column(
        SQLEnum(
            ExamOperationSource,
            name="exam_operation_source",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=True,
    )
    operation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    operation_requested_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    operation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    last_operation_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    operation_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    result_disposition: Mapped[ExamResultDisposition | None] = mapped_column(
        SQLEnum(
            ExamResultDisposition,
            name="exam_result_disposition",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=True,
    )
    results_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    results_decided_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    results_decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "operation_attempts >= 0",
            name="ck_exam_execution_controls_attempts_nonnegative",
        ),
        CheckConstraint(
            "operation_error IS NULL OR "
            f"char_length(operation_error) <= {EXECUTION_ERROR_MAX_LENGTH}",
            name="ck_exam_execution_controls_error_length",
        ),
        CheckConstraint(
            "(operation IS NULL) OR "
            "(operation_source IS NOT NULL AND operation_requested_at IS NOT NULL)",
            name="ck_exam_execution_controls_operation_metadata",
        ),
        CheckConstraint(
            "operation_source != 'admin' OR operation_requested_by_actor_id IS NOT NULL",
            name="ck_exam_execution_controls_admin_actor",
        ),
        CheckConstraint(
            "operation != 'cancelling' OR operation_reason IS NOT NULL",
            name="ck_exam_execution_controls_cancel_reason",
        ),
        CheckConstraint(
            "result_disposition NOT IN ('approved', 'voided') OR "
            "(results_decided_at IS NOT NULL AND results_decided_by_actor_id IS NOT NULL)",
            name="ck_exam_execution_controls_result_decision_metadata",
        ),
        CheckConstraint(
            "results_decision_reason IS NULL OR "
            f"char_length(results_decision_reason) <= {RESULT_DECISION_REASON_MAX_LENGTH}",
            name="ck_exam_execution_controls_result_reason_length",
        ),
        Index(
            "ix_exam_execution_controls_operation_requested",
            "operation",
            "operation_requested_at",
        ),
        Index(
            "ix_exam_execution_controls_result_disposition",
            "result_disposition",
            "exam_id",
        ),
    )
