"""Durable opaque student waiting-room and examination sessions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

STUDENT_SESSION_TOKEN_HASH_LENGTH = 64
STUDENT_SESSION_REASON_MAX_LENGTH = 500


class StudentExamSession(Base):
    """Opaque student session that may be waiting-room-only or exam-bound."""

    __tablename__ = "student_exam_sessions"

    student_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("exam_candidates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    exam_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("exams.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    makeup_authorization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("candidate_make_up_authorizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(STUDENT_SESSION_TOKEN_HASH_LENGTH),
        nullable=False,
        unique=True,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(STUDENT_SESSION_REASON_MAX_LENGTH), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at", name="ck_student_exam_sessions_valid_expiry"
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_student_exam_sessions_valid_revocation",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revocation_reason IS NOT NULL",
            name="ck_student_exam_sessions_revocation_reason_required",
        ),
        CheckConstraint(
            "(candidate_id IS NULL AND exam_id IS NULL) OR "
            "(candidate_id IS NOT NULL AND exam_id IS NOT NULL)",
            name="ck_student_exam_sessions_binding_pair",
        ),
        CheckConstraint(
            "makeup_authorization_id IS NULL OR candidate_id IS NOT NULL",
            name="ck_student_exam_sessions_makeup_requires_binding",
        ),
        Index(
            "uq_student_exam_sessions_one_active_candidate",
            "candidate_id",
            unique=True,
            postgresql_where=sql_text(
                "revoked_at IS NULL AND candidate_id IS NOT NULL"
            ),
        ),
        Index("ix_student_exam_sessions_student_expiry", "student_id", "expires_at"),
    )
