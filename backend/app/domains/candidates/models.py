"""Candidate models for Weave CBT."""

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

ADMISSION_NUMBER_MAX_LENGTH = 128
NAME_MAX_LENGTH = 255
STATUS_REASON_MAX_LENGTH = 500


class CandidateStatus(StrEnum):
    """Eligibility state of a candidate on one examination roster."""

    ELIGIBLE = "eligible"
    BLOCKED = "blocked"
    WITHDRAWN = "withdrawn"


class ExamCandidate(Base):
    """Materialized examination-roster snapshot."""

    __tablename__ = "exam_candidates"

    exam_id: Mapped[UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrollment_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_enrollments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    admission_number: Mapped[str] = mapped_column(
        String(ADMISSION_NUMBER_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    status: Mapped[CandidateStatus] = mapped_column(
        SQLEnum(
            CandidateStatus,
            name="candidate_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=CandidateStatus.ELIGIBLE,
        server_default=CandidateStatus.ELIGIBLE.value,
        index=True,
    )
    status_reason: Mapped[str | None] = mapped_column(
        String(STATUS_REASON_MAX_LENGTH), nullable=True
    )
    roster_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sql_text("1"),
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "exam_id",
            "enrollment_id",
            name="uq_exam_candidates_exam_enrollment",
        ),
        UniqueConstraint(
            "exam_id",
            "student_id",
            name="uq_exam_candidates_exam_student",
        ),
        UniqueConstraint(
            "exam_id",
            "admission_number",
            name="uq_exam_candidates_exam_admission_number",
        ),
        CheckConstraint(
            "roster_version >= 1",
            name="ck_exam_candidates_roster_version_positive",
        ),
        Index("ix_exam_candidates_exam_status", "exam_id", "status"),
        Index(
            "ix_exam_candidates_exam_class_status",
            "exam_id",
            "class_id",
            "status",
        ),
        Index(
            "ix_exam_candidates_exam_roster_version",
            "exam_id",
            "roster_version",
        ),
        Index(
            "ix_exam_candidates_eligible_student_exam",
            "student_id",
            "exam_id",
            postgresql_where=sql_text("status = 'eligible'"),
        ),
    )


class CandidateLateStartAuthorization(Base):
    """Administrative permission for one candidate to start an exam late."""

    __tablename__ = "candidate_late_start_authorizations"

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("exam_candidates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    granted_by_actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "expires_at IS NULL OR expires_at >= granted_at",
            name="ck_candidate_late_start_expiry_valid",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= granted_at",
            name="ck_candidate_late_start_consumed_valid",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="ck_candidate_late_start_revoked_valid",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_by_actor_id IS NOT NULL",
            name="ck_candidate_late_start_revocation_actor_required",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revocation_reason IS NOT NULL",
            name="ck_candidate_late_start_revocation_reason_required",
        ),
        CheckConstraint(
            "NOT (consumed_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_candidate_late_start_not_consumed_and_revoked",
        ),
        Index(
            "ix_candidate_late_start_candidate_granted",
            "candidate_id",
            "granted_at",
        ),
    )


class CandidateMakeupAuthorization(Base):
    """Administrative approval for one candidate's future makeup attempt."""

    __tablename__ = "candidate_make_up_authorizations"

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("exam_candidates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    approved_by_actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(
        String(STATUS_REASON_MAX_LENGTH), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(STATUS_REASON_MAX_LENGTH), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_candidate_makeup_one_active",
            "candidate_id",
            unique=True,
            postgresql_where=sql_text("revoked_at IS NULL"),
        ),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= approved_at",
            name="ck_candidate_makeup_consumed_valid",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= approved_at",
            name="ck_candidate_makeup_revoked_valid",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_by_actor_id IS NOT NULL",
            name="ck_candidate_makeup_revocation_actor_required",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revocation_reason IS NOT NULL",
            name="ck_candidate_makeup_revocation_reason_required",
        ),
        CheckConstraint(
            "NOT (consumed_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_candidate_makeup_not_consumed_and_revoked",
        ),
        Index(
            "ix_candidate_makeup_candidate_approved",
            "candidate_id",
            "approved_at",
        ),
    )
