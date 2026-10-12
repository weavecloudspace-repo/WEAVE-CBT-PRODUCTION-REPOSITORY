"""Local academic projections synchronized from Weave Cloud v5.

These rows are read-only projections from Weave. Their primary keys are the
Weave UUIDs supplied by the synchronization contract. Local CBT-owned domains
may reference them, so disappearing Cloud rows are tombstoned rather than
physically deleted.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

NAME_MAX_LENGTH = 255
STATUS_MAX_LENGTH = 64
CODE_MAX_LENGTH = 64
ADMISSION_NUMBER_MAX_LENGTH = 128
STAFF_ID_MAX_LENGTH = 128
EMAIL_MAX_LENGTH = 255
CATEGORY_MAX_LENGTH = 64
TIMEZONE_MAX_LENGTH = 128
INSTITUTION_TYPE_MAX_LENGTH = 64


class WeaveProjectionMixin:
    """Common synchronization metadata for Weave-owned projection rows."""

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    source_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class SchoolProfile(WeaveProjectionMixin, Base):
    __tablename__ = "school_profiles"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    institution_type: Mapped[str | None] = mapped_column(
        String(INSTITUTION_TYPE_MAX_LENGTH), nullable=True
    )
    timezone: Mapped[str] = mapped_column(String(TIMEZONE_MAX_LENGTH), nullable=False)


class AcademicSession(WeaveProjectionMixin, Base):
    __tablename__ = "academic_sessions"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(
        String(STATUS_MAX_LENGTH), nullable=False, index=True
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), index=True
    )

    __table_args__ = (
        Index("ix_academic_sessions_current_status", "is_current", "status"),
    )


class AcademicTerm(WeaveProjectionMixin, Base):
    __tablename__ = "academic_terms"

    academic_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(
        String(STATUS_MAX_LENGTH), nullable=False, index=True
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), index=True
    )

    __table_args__ = (
        Index("ix_academic_terms_session_current", "academic_session_id", "is_current"),
    )


class AcademicLevel(WeaveProjectionMixin, Base):
    __tablename__ = "academic_levels"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    category: Mapped[str] = mapped_column(
        String(CATEGORY_MAX_LENGTH), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    specialization_required_from_term_position: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "position >= 0", name="ck_academic_levels_position_nonnegative"
        ),
        CheckConstraint(
            "specialization_required_from_term_position IS NULL OR "
            "specialization_required_from_term_position BETWEEN 1 AND 3",
            name="ck_academic_levels_specialization_term_position",
        ),
        Index("ix_academic_levels_category_position", "category", "position"),
    )


class ArmLabel(WeaveProjectionMixin, Base):
    __tablename__ = "arm_labels"

    label: Mapped[str] = mapped_column(String(CODE_MAX_LENGTH), nullable=False)

    __table_args__ = (
        Index(
            "uq_arm_labels_current_label",
            "label",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
    )


class Department(WeaveProjectionMixin, Base):
    __tablename__ = "departments"

    academic_level_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_levels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)

    __table_args__ = (
        Index(
            "uq_departments_current_level_name",
            "academic_level_id",
            "name",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index("ix_departments_level_name", "academic_level_id", "name"),
    )


class AcademicClass(WeaveProjectionMixin, Base):
    __tablename__ = "academic_classes"

    academic_level_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_levels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    arm_label_id: Mapped[UUID] = mapped_column(
        ForeignKey("arm_labels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), index=True
    )

    __table_args__ = (
        Index(
            "uq_academic_classes_current_level_arm_label",
            "academic_level_id",
            "arm_label_id",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index("ix_academic_classes_level_active", "academic_level_id", "is_active"),
    )


class ClassTermDepartment(WeaveProjectionMixin, Base):
    __tablename__ = "class_term_departments"

    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    academic_term_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_terms.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    __table_args__ = (
        Index(
            "uq_class_term_departments_current_class_term",
            "class_id",
            "academic_term_id",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index(
            "ix_class_term_departments_term_department",
            "academic_term_id",
            "department_id",
        ),
    )


class AcademicSubject(WeaveProjectionMixin, Base):
    __tablename__ = "academic_subjects"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    code: Mapped[str | None] = mapped_column(String(CODE_MAX_LENGTH), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), index=True
    )


class Curriculum(WeaveProjectionMixin, Base):
    __tablename__ = "curricula"

    academic_level_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_levels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index(
            "uq_curricula_current_level",
            "academic_level_id",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
    )


class CurriculumSubject(WeaveProjectionMixin, Base):
    __tablename__ = "curriculum_subjects"

    curriculum_id: Mapped[UUID] = mapped_column(
        ForeignKey("curricula.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_elective: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), index=True
    )
    elective_group_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), index=True
    )

    __table_args__ = (
        Index(
            "uq_curriculum_subjects_current_curriculum_subject",
            "curriculum_id",
            "subject_id",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index("ix_curriculum_subjects_curriculum_active", "curriculum_id", "is_active"),
    )


class CurriculumSubjectDepartment(WeaveProjectionMixin, Base):
    """Department applicability for one synchronized curriculum subject.

    No live rows for a curriculum subject means the subject is general. One or
    more live rows make it specialization-scoped to the referenced level-specific
    department identities.
    """

    __tablename__ = "curriculum_subject_departments"

    curriculum_subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "uq_curriculum_subject_departments_current_scope",
            "curriculum_subject_id",
            "department_id",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index(
            "ix_curriculum_subject_departments_live_subject",
            "curriculum_subject_id",
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index(
            "ix_curriculum_subject_departments_live_department",
            "department_id",
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
    )


class StudentElectiveSelection(WeaveProjectionMixin, Base):
    """Authoritative current elective choice projected from Weave.

    Selection rows are current intent, not historical exam evidence. CBT uses
    them only while deriving or reconciling pre-execution candidate rosters.
    Once an exam begins, the frozen candidate/attempt/result records remain the
    local execution truth even if a later Cloud selection changes.
    """

    __tablename__ = "student_elective_selections"

    student_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    elective_group_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    curriculum_subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index(
            "uq_student_elective_selections_live_student_subject",
            "student_id",
            "curriculum_subject_id",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index(
            "ix_student_elective_selections_live_group_student",
            "elective_group_id",
            "student_id",
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index(
            "ix_student_elective_selections_live_subject_student",
            "curriculum_subject_id",
            "student_id",
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
    )


class AssessmentScheme(WeaveProjectionMixin, Base):
    __tablename__ = "assessment_schemes"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(
        String(STATUS_MAX_LENGTH), nullable=False, index=True
    )


class AssessmentComponent(WeaveProjectionMixin, Base):
    __tablename__ = "assessment_components"

    assessment_scheme_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment_schemes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    code: Mapped[str | None] = mapped_column(String(CODE_MAX_LENGTH), nullable=True)
    maximum_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), index=True
    )

    __table_args__ = (
        Index(
            "uq_assessment_components_current_scheme_position",
            "assessment_scheme_id",
            "position",
            unique=True,
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        CheckConstraint(
            "maximum_score > 0", name="ck_assessment_components_maximum_positive"
        ),
        CheckConstraint(
            "position >= 0", name="ck_assessment_components_position_nonnegative"
        ),
        Index(
            "ix_assessment_components_scheme_active",
            "assessment_scheme_id",
            "is_active",
        ),
    )


class AcademicAdmin(WeaveProjectionMixin, Base):
    __tablename__ = "academic_admins"

    email: Mapped[str] = mapped_column(
        String(EMAIL_MAX_LENGTH), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(STATUS_MAX_LENGTH), nullable=False, index=True
    )


class AcademicTeacher(WeaveProjectionMixin, Base):
    __tablename__ = "academic_teachers"

    teacher_account_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(
        String(NAME_MAX_LENGTH), nullable=True
    )
    last_name: Mapped[str | None] = mapped_column(
        String(NAME_MAX_LENGTH), nullable=True
    )
    staff_id: Mapped[str | None] = mapped_column(
        String(STAFF_ID_MAX_LENGTH), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(STATUS_MAX_LENGTH), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_academic_teachers_status_name", "status", "last_name", "first_name"),
    )


class TeacherAssignment(WeaveProjectionMixin, Base):
    __tablename__ = "teacher_assignments"

    teacher_membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    curriculum_subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    __table_args__ = (
        Index(
            "ix_teacher_assignments_live_teacher_effective",
            "teacher_membership_id",
            "effective_from",
            "effective_to",
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        Index(
            "ix_teacher_assignments_live_scope_effective",
            "class_id",
            "curriculum_subject_id",
            "effective_from",
            "effective_to",
            postgresql_where=text("source_deleted_at IS NULL"),
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_teacher_assignments_effective_range",
        ),
    )


class StudentEnrollment(WeaveProjectionMixin, Base):
    __tablename__ = "student_enrollments"

    student_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    admission_number: Mapped[str] = mapped_column(
        String(ADMISSION_NUMBER_MAX_LENGTH), nullable=False, index=True
    )
    first_name: Mapped[str | None] = mapped_column(
        String(NAME_MAX_LENGTH), nullable=True
    )
    last_name: Mapped[str | None] = mapped_column(
        String(NAME_MAX_LENGTH), nullable=True
    )
    academic_level_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_levels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    class_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("academic_classes.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    academic_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("academic_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), index=True
    )
    student_status: Mapped[str] = mapped_column(
        String(STATUS_MAX_LENGTH), nullable=False, index=True
    )

    __table_args__ = (
        Index(
            "uq_student_enrollments_current_student",
            "student_id",
            unique=True,
            postgresql_where=text("is_current = true AND source_deleted_at IS NULL"),
        ),
        Index(
            "ix_student_enrollments_live_class",
            "class_id",
            postgresql_where=text("is_current = true AND source_deleted_at IS NULL"),
        ),
        Index(
            "ix_student_enrollments_live_session",
            "academic_session_id",
            postgresql_where=text("is_current = true AND source_deleted_at IS NULL"),
        ),
    )
