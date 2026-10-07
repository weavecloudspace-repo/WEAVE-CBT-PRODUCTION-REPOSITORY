# =========================== #
#       results/models.py     #
# =========================== #

"""Database models for locally calculated CBT assessment results."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

RESULT_SYNC_ERROR_MAX_LENGTH = 1024


# ========================== #
# ENUMS
# ========================== #


class ResultSyncStatus(str, PyEnum):
    """
    Synchronization state of a locally calculated CBT result.

    PENDING
        Result exists locally but has not yet been synchronized to Weave.

    SYNCING
        A worker is currently attempting synchronization.

    SYNCED
        Weave successfully accepted the assessment-component result.

    FAILED
        The latest synchronization attempt failed and may be retried.
    """

    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    FAILED = "failed"


# ========================== #
# EXAM RESULT
# ========================== #


class ExamResult(Base):
    """
    Final locally calculated result for one candidate examination attempt.

    CBT preserves two different score representations:

        RAW EXAM SCORE

            raw_score
            raw_max_score

        WEAVE ASSESSMENT-COMPONENT SCORE

            component_score
            component_maximum_score

    Example:

        Exam contains 40 questions.

        Candidate answers 32 correctly.

        Assessment component:
            CA1
            maximum score = 10

        Stored result:

            raw_score = 32
            raw_max_score = 40

            percentage = 80.00

            component_score = 8.00
            component_maximum_score = 10.00

    The local CBT UI can therefore display:

        32 / 40
        80 / 100
        8 / 10

    Weave receives the component score, not the raw CBT question count.

    One ExamAttempt produces at most one ExamResult.
    """

    __tablename__ = "exam_results"

    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "exam_attempts.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
        index=True,
    )

    # Snapshotted references make result querying and synchronization
    # straightforward without repeatedly traversing:
    #
    # result -> attempt -> candidate -> exam
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "exam_candidates.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    exam_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "exams.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    assessment_component_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "assessment_components.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    # ========================== #
    # RAW CBT SCORE
    # ========================== #

    # Number of questions answered correctly.
    #
    # Since every question contributes exactly one raw mark,
    # this is always an integer.
    raw_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Number of frozen ExamQuestion rows in the paper.
    raw_max_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Normalized raw score over 100.
    #
    # Example:
    # 32 / 40 = 80.00
    percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )

    # ========================== #
    # ASSESSMENT COMPONENT SCORE
    # ========================== #

    # Score normalized against the frozen Weave assessment-component
    # maximum.
    #
    # Example:
    #
    # raw = 32 / 40
    # component maximum = 10
    #
    # component_score = 8.00
    component_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        nullable=False,
    )

    # Frozen component maximum from the Exam.
    #
    # This must not be re-read from current synchronized academics when
    # calculating historical results because Weave configuration may have
    # changed after the exam was sealed.
    component_maximum_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        nullable=False,
    )

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ========================== #
    # WEAVE SYNC
    # ========================== #

    sync_status: Mapped[ResultSyncStatus] = mapped_column(
        SQLEnum(
            ResultSyncStatus,
            name="result_sync_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=ResultSyncStatus.PENDING,
        server_default=ResultSyncStatus.PENDING.value,
        index=True,
    )

    # Stable Weave ingestion batch containing this result
    # Weave performs CBT result ingestion in batches rather than assigning
    # an independent idempotency key to every local result
    # The batch UUID is persisted before the newtork request is made so an
    # uncertain retry after timeout, crash or power loss can reconstruct
    # and resend the exact same logical batch

    sync_batch_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)

    sync_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )

    last_sync_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sync_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Preserve calculated scores as evidence; voiding only removes publication eligibility.
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT")
    )
    void_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "(voided_at IS NULL AND voided_by_actor_id IS NULL AND void_reason IS NULL) OR "
            "(voided_at IS NOT NULL AND voided_by_actor_id IS NOT NULL AND "
            "void_reason IS NOT NULL AND char_length(trim(void_reason)) BETWEEN 1 AND 1024)",
            name="ck_exam_results_void_audit",
        ),
        CheckConstraint(
            "voided_at IS NULL OR (sync_batch_id IS NULL AND sync_status IN ('pending', 'failed'))",
            name="ck_exam_results_void_unsent",
        ),
        UniqueConstraint(
            "candidate_id",
            "exam_id",
            name="uq_exam_results_candidate_exam",
        ),
        # ========================== #
        # RAW SCORE CONSTRAINTS
        # ========================== #
        CheckConstraint(
            "raw_score >= 0",
            name="ck_exam_results_raw_score_nonnegative",
        ),
        CheckConstraint(
            "raw_max_score > 0",
            name="ck_exam_results_raw_max_positive",
        ),
        CheckConstraint(
            "raw_score <= raw_max_score",
            name="ck_exam_results_raw_score_within_max",
        ),
        # ========================== #
        # PERCENTAGE CONSTRAINTS
        # ========================== #
        CheckConstraint(
            "percentage >= 0",
            name="ck_exam_results_percentage_nonnegative",
        ),
        CheckConstraint(
            "percentage <= 100",
            name="ck_exam_results_percentage_within_100",
        ),
        # ========================== #
        # COMPONENT SCORE CONSTRAINTS
        # ========================== #
        CheckConstraint(
            "component_score >= 0",
            name="ck_exam_results_component_score_nonnegative",
        ),
        CheckConstraint(
            "component_maximum_score > 0",
            name="ck_exam_results_component_max_positive",
        ),
        CheckConstraint(
            "component_score <= component_maximum_score",
            name="ck_exam_results_component_score_within_max",
        ),
        # ========================== #
        # SYNC CONSTRAINTS
        # ========================== #
        CheckConstraint(
            "sync_attempts >= 0",
            name="ck_exam_results_sync_attempts_nonnegative",
        ),
        CheckConstraint(
            "sync_error IS NULL OR "
            f"char_length(sync_error) <= {RESULT_SYNC_ERROR_MAX_LENGTH}",
            name="ck_exam_results_sync_error_length",
        ),
        CheckConstraint(
            "synced_at IS NULL OR sync_status = 'synced'",
            name="ck_exam_results_synced_at_matches_status",
        ),
        CheckConstraint(
            "sync_status != 'syncing' OR sync_batch_id IS NOT NULL",
            name="ck_exam_results_syncing_requires_batch",
        ),
        CheckConstraint(
            "sync_status != 'synced' OR sync_batch_id IS NOT NULL",
            name="ck_exam_results_synced_requires_batch",
        ),
        # ========================== #
        # INDEXES
        # ========================== #
        Index(
            "ix_exam_results_exam_sync_status",
            "exam_id",
            "sync_status",
        ),
        Index(
            "ix_exam_results_component_sync_status",
            "assessment_component_id",
            "sync_status",
        ),
        Index(
            "ix_exam_results_sync_status_attempt",
            "sync_status",
            "last_sync_attempt_at",
        ),
        Index("ix_exam_results_sync_batch_status", "sync_batch_id", "sync_status"),
    )
