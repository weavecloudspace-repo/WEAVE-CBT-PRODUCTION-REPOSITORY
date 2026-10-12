"""Database models for candidate examination attempts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
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
from app.domains.questions.models import QuestionType

ATTEMPT_REASON_MAX_LENGTH = 500


class AttemptStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    INTERRUPTED = "interrupted"
    SUBMITTED = "submitted"
    TERMINATED = "terminated"


class AttemptEndReason(StrEnum):
    CANDIDATE_SUBMITTED = "candidate_submitted"
    TIME_EXPIRED = "time_expired"
    EXAM_CLOSED = "exam_closed"
    EXAM_CANCELLED = "exam_cancelled"
    ADMIN_TERMINATED = "admin_terminated"


class ExamAttempt(Base):
    """One durable attempt for one exact ExamCandidate."""

    __tablename__ = "exam_attempts"

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("exam_candidates.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[AttemptStatus] = mapped_column(
        SQLEnum(
            AttemptStatus,
            name="attempt_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=AttemptStatus.IN_PROGRESS,
        server_default=AttemptStatus.IN_PROGRESS.value,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    active_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_reason: Mapped[AttemptEndReason | None] = mapped_column(
        SQLEnum(
            AttemptEndReason,
            name="attempt_end_reason",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=True,
    )
    termination_reason: Mapped[str | None] = mapped_column(
        String(ATTEMPT_REASON_MAX_LENGTH), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "time_limit_seconds > 0", name="ck_exam_attempts_time_limit_positive"
        ),
        CheckConstraint(
            "elapsed_seconds >= 0", name="ck_exam_attempts_elapsed_nonnegative"
        ),
        CheckConstraint(
            "elapsed_seconds <= time_limit_seconds",
            name="ck_exam_attempts_elapsed_within_limit",
        ),
        CheckConstraint(
            "active_since IS NULL OR active_since >= started_at",
            name="ck_exam_attempts_valid_active_since",
        ),
        CheckConstraint(
            "last_heartbeat_at >= started_at",
            name="ck_exam_attempts_valid_heartbeat",
        ),
        CheckConstraint(
            "last_activity_at >= started_at",
            name="ck_exam_attempts_valid_activity",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_exam_attempts_valid_end",
        ),
        CheckConstraint(
            "(status = 'in_progress' AND active_since IS NOT NULL) "
            "OR (status <> 'in_progress' AND active_since IS NULL)",
            name="ck_exam_attempts_active_segment_matches_status",
        ),
        CheckConstraint(
            "("
            "status IN ('in_progress', 'interrupted') "
            "AND ended_at IS NULL "
            "AND end_reason IS NULL"
            ") OR ("
            "status IN ('submitted', 'terminated') "
            "AND ended_at IS NOT NULL "
            "AND end_reason IS NOT NULL"
            ")",
            name="ck_exam_attempts_terminal_state_consistent",
        ),
        CheckConstraint(
            "("
            "status = 'terminated' "
            "AND end_reason IN ('admin_terminated', 'exam_cancelled') "
            "AND termination_reason IS NOT NULL"
            ") OR ("
            "status <> 'terminated' "
            "AND termination_reason IS NULL"
            ")",
            name="ck_exam_attempts_termination_reason_consistent",
        ),
        CheckConstraint(
            "status <> 'submitted' OR "
            "end_reason NOT IN ('admin_terminated', 'exam_cancelled')",
            name="ck_exam_attempts_submitted_not_admin_terminated",
        ),
        Index("ix_exam_attempts_status_heartbeat", "status", "last_heartbeat_at"),
    )


class AttemptInterruption(Base):
    """Durable history for one candidate-specific interruption."""

    __tablename__ = "attempt_interruptions"

    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("exam_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    interrupted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    remaining_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(
        String(ATTEMPT_REASON_MAX_LENGTH), nullable=False
    )
    resumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resumed_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    resume_reason: Mapped[str | None] = mapped_column(
        String(ATTEMPT_REASON_MAX_LENGTH), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "remaining_seconds >= 0",
            name="ck_attempt_interruptions_remaining_nonnegative",
        ),
        CheckConstraint(
            "resumed_at IS NULL OR resumed_at >= interrupted_at",
            name="ck_attempt_interruptions_valid_resume",
        ),
        CheckConstraint(
            "resumed_at IS NULL OR resumed_by_actor_id IS NOT NULL",
            name="ck_attempt_interruptions_resume_actor_required",
        ),
        CheckConstraint(
            "resumed_at IS NULL OR resume_reason IS NOT NULL",
            name="ck_attempt_interruptions_resume_reason_required",
        ),
        Index(
            "uq_attempt_interruptions_one_open",
            "attempt_id",
            unique=True,
            postgresql_where=sql_text("resumed_at IS NULL"),
        ),
        Index(
            "ix_attempt_interruptions_attempt_interrupted",
            "attempt_id",
            "interrupted_at",
        ),
    )


class AttemptQuestionAllocation(Base):
    """
    Immutable candidate-specific question snapshot.

    Normal attempts copy the already sealed ExamQuestion snapshot.
    Makeup attempts copy a fresh randomly selected source Question.

    The presentation position and question content therefore survive refresh,
    reconnect, source-bank edits, and server restart without regenerating the
    paper.
    """

    __tablename__ = "attempt_question_allocations"

    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("exam_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exam_question_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("exam_questions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_question_version: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(
        SQLEnum(
            QuestionType,
            name="attempt_question_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "source_question_id",
            name="uq_attempt_questions_attempt_source_question",
        ),
        UniqueConstraint(
            "attempt_id",
            "position",
            name="uq_attempt_questions_attempt_position",
        ),
        CheckConstraint(
            "source_question_version >= 1",
            name="ck_attempt_questions_source_version_positive",
        ),
        CheckConstraint("position >= 1", name="ck_attempt_questions_position_positive"),
        Index(
            "ix_attempt_questions_attempt_position",
            "attempt_id",
            "position",
        ),
    )


class AttemptOptionAllocation(Base):
    """
    Immutable candidate-specific answer-option snapshot.

    Exactly one provenance reference is present:
      * exam_question_option_id for a normal sealed paper;
      * source_question_option_id for a fresh makeup paper.

    Correctness is persisted locally for offline scoring but never exposed in
    candidate response schemas.
    """

    __tablename__ = "attempt_option_allocations"

    attempt_question_id: Mapped[UUID] = mapped_column(
        ForeignKey("attempt_question_allocations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exam_question_option_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("exam_question_options.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_question_option_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_options.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    is_correct: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )

    __table_args__ = (
        UniqueConstraint(
            "attempt_question_id",
            "position",
            name="uq_attempt_options_question_position",
        ),
        CheckConstraint(
            "(exam_question_option_id IS NOT NULL "
            "AND source_question_option_id IS NULL) "
            "OR (exam_question_option_id IS NULL "
            "AND source_question_option_id IS NOT NULL)",
            name="ck_attempt_options_exactly_one_source",
        ),
        CheckConstraint(
            "text IS NOT NULL OR image_asset_id IS NOT NULL",
            name="ck_attempt_options_content_required",
        ),
        CheckConstraint("position >= 1", name="ck_attempt_options_position_positive"),
        Index(
            "uq_attempt_options_exam_source",
            "attempt_question_id",
            "exam_question_option_id",
            unique=True,
            postgresql_where=sql_text("exam_question_option_id IS NOT NULL"),
        ),
        Index(
            "uq_attempt_options_bank_source",
            "attempt_question_id",
            "source_question_option_id",
            unique=True,
            postgresql_where=sql_text("source_question_option_id IS NOT NULL"),
        ),
        Index(
            "ix_attempt_options_question_position",
            "attempt_question_id",
            "position",
        ),
    )


class AttemptAnswer(Base):
    """Current durable answer state for one allocated attempt question."""

    __tablename__ = "attempt_answers"

    attempt_question_id: Mapped[UUID] = mapped_column(
        ForeignKey("attempt_question_allocations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    is_flagged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    mutation_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "mutation_sequence >= 0",
            name="ck_attempt_answers_mutation_sequence_nonnegative",
        ),
        Index("ix_attempt_answers_updated", "updated_at"),
    )


class AttemptAnswerSelection(Base):
    """One currently selected candidate option for an AttemptAnswer."""

    __tablename__ = "attempt_answer_selections"

    answer_id: Mapped[UUID] = mapped_column(
        ForeignKey("attempt_answers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_option_id: Mapped[UUID] = mapped_column(
        ForeignKey("attempt_option_allocations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "answer_id",
            "attempt_option_id",
            name="uq_attempt_answer_selections_answer_option",
        ),
        Index("ix_attempt_answer_selections_answer", "answer_id"),
    )
