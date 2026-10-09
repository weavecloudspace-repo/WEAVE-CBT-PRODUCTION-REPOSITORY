"""Database models for locally owned CBT examinations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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

EXAM_TITLE_MAX_LENGTH = 255
WEAVE_ID_MAX_LENGTH = 128
ROSTER_ERROR_MAX_LENGTH = 1024


# ========================== #
# ENUMS
# ========================== #


class ExamStatus(StrEnum):
    """Lifecycle state of a local CBT examination."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    SEALED = "sealed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSING = "closing"
    CANCELLING = "cancelling"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ExamRosterStatus(StrEnum):
    """Materialization state of the examination candidate roster."""

    NOT_PREPARED = "not_prepared"
    PENDING = "pending"
    BUILDING = "building"
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"


class ExamQuestionSelectionMode(StrEnum):
    """Defines how questions are chosen for an examination."""

    RANDOM = "random"
    MANUAL = "manual"


class ExamSuspensionSource(StrEnum):
    """Origin of an examination-wide suspension."""

    ADMIN = "admin"
    SYSTEM = "system"


# ========================== #
# EXAM
# ========================== #


class Exam(Base):
    """Locally owned, level-wide CBT examination."""

    __tablename__ = "exams"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    term_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_terms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    curriculum_subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    question_bank_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    question_selection_mode: Mapped[ExamQuestionSelectionMode] = mapped_column(
        SQLEnum(
            ExamQuestionSelectionMode,
            name="exam_question_selection_mode",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=ExamQuestionSelectionMode.RANDOM,
        server_default=ExamQuestionSelectionMode.RANDOM.value,
        index=True,
    )

    question_count: Mapped[int] = mapped_column(Integer, nullable=False)

    assessment_scheme_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment_schemes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    assessment_component_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment_components.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(EXAM_TITLE_MAX_LENGTH),
        nullable=False,
    )

    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Presentation-only identity for the folder-style exam card. Existing rows
    # may remain NULL and use the frontend's deterministic fallback colour.
    folder_color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    shuffle_questions: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
    )

    shuffle_options: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
    )

    status: Mapped[ExamStatus] = mapped_column(
        SQLEnum(
            ExamStatus,
            name="exam_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=ExamStatus.DRAFT,
        server_default=ExamStatus.DRAFT.value,
        index=True,
    )

    scheduled_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    latest_normal_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    roster_status: Mapped[ExamRosterStatus] = mapped_column(
        SQLEnum(
            ExamRosterStatus,
            name="exam_roster_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=ExamRosterStatus.NOT_PREPARED,
        server_default=ExamRosterStatus.NOT_PREPARED.value,
        index=True,
    )

    roster_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )

    roster_candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )

    roster_prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    roster_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Monotonic collaboration version for the mutable draft paper. Every
    # successful authoring mutation increments this value. Clients send the
    # version they last read so stale screens cannot overwrite newer work.
    authoring_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sql_text("1"),
    )

    revision_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sql_text("1"),
    )

    revision_of_exam_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("exams.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
        index=True,
    )

    # Immutable provenance: who originally created this revision. Authoring
    # leadership is stored separately so an administrator-created paper can be
    # coordinated by an eligible teacher without rewriting its provenance.
    created_by_actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # NULL means the paper is administrator-led. A teacher ID means that
    # synchronized academic teacher is the current coordinating lead. Using the
    # academic projection ID (rather than a LocalActor ID) allows an admin to
    # assign a teacher before that teacher has logged into this CBT server.
    lead_teacher_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("academic_teachers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    lead_assigned_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    lead_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sealed_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    sealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    activated_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    component_maximum_score: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2),
        nullable=True,
    )

    weave_calendar_event_id: Mapped[str | None] = mapped_column(
        String(WEAVE_ID_MAX_LENGTH),
        nullable=True,
        unique=True,
        index=True,
    )

    calendar_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "question_count > 0",
            name="ck_exams_question_count_positive",
        ),
        Index(
            "uq_exams_scope_revision",
            "term_id",
            "curriculum_subject_id",
            "assessment_component_id",
            "revision_number",
            unique=True,
        ),
        CheckConstraint(
            "duration_minutes > 0",
            name="ck_exams_duration_positive",
        ),
        CheckConstraint(
            "authoring_version >= 1",
            name="ck_exams_authoring_version_positive",
        ),
        CheckConstraint(
            "revision_number >= 1",
            name="ck_exams_revision_positive",
        ),
        CheckConstraint(
            "(revision_of_exam_id IS NULL AND revision_number = 1) OR "
            "(revision_of_exam_id IS NOT NULL AND revision_number > 1)",
            name="ck_exams_revision_lineage_shape",
        ),
        CheckConstraint(
            "roster_version >= 0",
            name="ck_exams_roster_version_nonnegative",
        ),
        CheckConstraint(
            "roster_candidate_count >= 0",
            name="ck_exams_roster_candidate_count_nonnegative",
        ),
        CheckConstraint(
            "roster_error IS NULL OR "
            f"char_length(roster_error) <= {ROSTER_ERROR_MAX_LENGTH}",
            name="ck_exams_roster_error_length",
        ),
        CheckConstraint(
            "latest_normal_start_at IS NULL OR scheduled_start_at IS NULL OR "
            "latest_normal_start_at >= scheduled_start_at",
            name="ck_exams_valid_normal_start_window",
        ),
        CheckConstraint(
            "component_maximum_score IS NULL OR component_maximum_score > 0",
            name="ck_exams_component_maximum_positive",
        ),
        CheckConstraint(
            "lead_assigned_at IS NULL OR lead_assigned_by_actor_id IS NOT NULL",
            name="ck_exams_lead_assignment_actor_required",
        ),
        CheckConstraint(
            "submitted_at IS NULL OR submitted_by_actor_id IS NOT NULL",
            name="ck_exams_submission_actor_required",
        ),
        CheckConstraint(
            "sealed_at IS NULL OR sealed_by_actor_id IS NOT NULL",
            name="ck_exams_sealing_actor_required",
        ),
        CheckConstraint(
            "activated_at IS NULL OR activated_by_actor_id IS NOT NULL",
            name="ck_exams_activation_actor_required",
        ),
        CheckConstraint(
            "cancelled_at IS NULL OR cancelled_by_actor_id IS NOT NULL",
            name="ck_exams_cancellation_actor_required",
        ),
        CheckConstraint(
            "cancelled_at IS NULL OR cancellation_reason IS NOT NULL",
            name="ck_exams_cancellation_reason_required",
        ),
        Index(
            "ix_exams_session_term_status",
            "session_id",
            "term_id",
            "status",
        ),
        Index(
            "ix_exams_curriculum_subject_status",
            "curriculum_subject_id",
            "status",
        ),
        Index(
            "ix_exams_component_status",
            "assessment_component_id",
            "status",
        ),
        Index(
            "ix_exams_roster_status_exam_status",
            "roster_status",
            "status",
        ),
        Index(
            "ix_exams_scheduled_status",
            "scheduled_start_at",
            "status",
        ),
    )


class ExamQuestionSelection(Base):
    """One source question selected for a MANUAL shared draft paper."""

    __tablename__ = "exam_question_selections"

    exam_id: Mapped[UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    added_by_actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "exam_id", "question_id", name="uq_exam_question_selections_exam_question"
        ),
        UniqueConstraint(
            "exam_id", "position", name="uq_exam_question_selections_exam_position"
        ),
        CheckConstraint(
            "position >= 1", name="ck_exam_question_selections_position_positive"
        ),
        Index("ix_exam_question_selections_exam_position", "exam_id", "position"),
    )


class ExamTargetClass(Base):
    """Concrete class delivery target derived from synchronized academics."""

    __tablename__ = "exam_target_classes"

    exam_id: Mapped[UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teacher_assignments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "exam_id", "class_id", name="uq_exam_target_classes_exam_class"
        ),
        Index("ix_exam_target_classes_class_exam", "class_id", "exam_id"),
        Index("ix_exam_target_classes_assignment", "teacher_assignment_id"),
    )


class ExamInvigilator(Base):
    """Teacher assigned to supervise an examination."""

    __tablename__ = "exam_invigilators"

    exam_id: Mapped[UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    teacher_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "exam_id", "teacher_id", name="uq_exam_invigilators_exam_teacher"
        ),
        Index("ix_exam_invigilators_teacher_exam", "teacher_id", "exam_id"),
    )


class ExamSuspension(Base):
    """Durable history of an examination-wide suspension."""

    __tablename__ = "exam_suspensions"

    exam_id: Mapped[UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[ExamSuspensionSource] = mapped_column(
        SQLEnum(
            ExamSuspensionSource,
            name="exam_suspension_source",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    suspended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    suspended_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resumed_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    resume_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "resumed_at IS NULL OR resumed_at >= suspended_at",
            name="ck_exam_suspensions_resume_after_suspend",
        ),
        CheckConstraint(
            "resumed_at IS NULL OR resumed_by_actor_id IS NOT NULL",
            name="ck_exam_suspensions_resume_actor_required",
        ),
        CheckConstraint(
            "(source != 'admin') OR (suspended_by_actor_id IS NOT NULL)",
            name="ck_exam_suspensions_admin_actor_required",
        ),
        Index("ix_exam_suspensions_exam_suspended_at", "exam_id", "suspended_at"),
    )


class ExamQuestion(Base):
    """Immutable question snapshot belonging to a sealed examination."""

    __tablename__ = "exam_questions"

    exam_id: Mapped[UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_question_version: Mapped[int] = mapped_column(Integer, nullable=False)
    added_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    question_type: Mapped[QuestionType] = mapped_column(
        SQLEnum(
            QuestionType,
            name="exam_question_type",
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
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "exam_id",
            "source_question_id",
            name="uq_exam_questions_exam_source_question",
        ),
        UniqueConstraint("exam_id", "position", name="uq_exam_questions_exam_position"),
        CheckConstraint(
            "source_question_version >= 1",
            name="ck_exam_questions_source_version_positive",
        ),
        CheckConstraint("position >= 1", name="ck_exam_questions_position_positive"),
        Index("ix_exam_questions_exam_position", "exam_id", "position"),
    )


class ExamQuestionOption(Base):
    """Immutable answer-option snapshot for a frozen ExamQuestion."""

    __tablename__ = "exam_question_options"

    exam_question_id: Mapped[UUID] = mapped_column(
        ForeignKey("exam_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    is_correct: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )

    __table_args__ = (
        UniqueConstraint(
            "exam_question_id",
            "position",
            name="uq_exam_question_options_question_position",
        ),
        CheckConstraint(
            "position >= 1", name="ck_exam_question_options_position_positive"
        ),
        CheckConstraint(
            "text IS NOT NULL OR image_asset_id IS NOT NULL",
            name="ck_exam_question_options_content_required",
        ),
        Index(
            "ix_exam_question_options_question_position", "exam_question_id", "position"
        ),
    )
