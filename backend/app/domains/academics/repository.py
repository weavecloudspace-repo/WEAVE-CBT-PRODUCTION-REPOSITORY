"""Persistence operations for Weave academic projections.

Repositories only read/write local PostgreSQL projections. They never call
Weave and never commit transactions. Synchronization policy belongs to the sync
domain; exam/question authorization belongs to their respective services.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.domains.academics.models import (
    AcademicAdmin,
    AcademicClass,
    AcademicLevel,
    AcademicSession,
    AcademicSubject,
    AcademicTeacher,
    AcademicTerm,
    ArmLabel,
    AssessmentComponent,
    AssessmentScheme,
    ClassTermDepartment,
    Curriculum,
    CurriculumSubject,
    CurriculumSubjectDepartment,
    Department,
    StudentEnrollment,
    TeacherAssignment,
)

ProjectionT = TypeVar("ProjectionT", bound=Base)
PROJECTION_WRITE_BATCH_SIZE = 1000

PROJECTION_MODELS: tuple[type[Base], ...] = (
    AcademicSession,
    AcademicTerm,
    AcademicLevel,
    ArmLabel,
    Department,
    AcademicClass,
    ClassTermDepartment,
    AcademicSubject,
    Curriculum,
    CurriculumSubject,
    CurriculumSubjectDepartment,
    AssessmentScheme,
    AssessmentComponent,
    AcademicAdmin,
    AcademicTeacher,
    TeacherAssignment,
    StudentEnrollment,
)


class AcademicRepository:
    """Data-access layer for current and historical Weave projections."""

    @staticmethod
    async def bulk_upsert_projections(
        db: AsyncSession,
        model: type[ProjectionT],
        rows: Sequence[dict[str, Any]],
        *,
        synced_at: datetime | None = None,
    ) -> None:
        """Upsert projection rows in bounded PostgreSQL batches.

        Chunking avoids PostgreSQL/asyncpg parameter-count ceilings for large
        schools while still reducing thousands of row-at-a-time flushes to a
        handful of set-based statements.
        """

        if not rows:
            return
        timestamp = synced_at or datetime.now(UTC)
        for start in range(0, len(rows), PROJECTION_WRITE_BATCH_SIZE):
            chunk = rows[start : start + PROJECTION_WRITE_BATCH_SIZE]
            values = [
                {
                    **row,
                    "synced_at": timestamp,
                    "source_deleted_at": None,
                }
                for row in chunk
            ]
            statement = pg_insert(model).values(values)
            mutable_columns = {
                key: getattr(statement.excluded, key)
                for key in values[0]
                if key != "id"
            }
            if "updated_at" in model.__table__.c:
                mutable_columns["updated_at"] = func.now()
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[model.id],
                    set_=mutable_columns,
                )
            )

    @classmethod
    async def upsert_projection(
        cls,
        db: AsyncSession,
        model: type[ProjectionT],
        entity_id: UUID,
        values: dict[str, Any],
        *,
        synced_at: datetime | None = None,
    ) -> ProjectionT:
        await cls.bulk_upsert_projections(
            db,
            model,
            [{"id": entity_id, **values}],
            synced_at=synced_at,
        )
        row = await db.get(model, entity_id)
        if row is None:
            raise RuntimeError(f"Failed to upsert {model.__name__} {entity_id}.")
        return row

    @staticmethod
    async def bulk_tombstone_projections(
        db: AsyncSession,
        model: type[ProjectionT],
        entity_ids: Sequence[UUID],
        *,
        deleted_at: datetime | None = None,
    ) -> None:
        unique_ids = tuple(dict.fromkeys(entity_ids))
        if not unique_ids:
            return
        timestamp = deleted_at or datetime.now(UTC)
        for start in range(0, len(unique_ids), PROJECTION_WRITE_BATCH_SIZE):
            chunk = unique_ids[start : start + PROJECTION_WRITE_BATCH_SIZE]
            await db.execute(
                update(model)
                .where(model.id.in_(chunk))
                .values(
                    source_deleted_at=timestamp,
                    updated_at=func.now(),
                )
            )

    @classmethod
    async def tombstone_projection(
        cls,
        db: AsyncSession,
        model: type[ProjectionT],
        entity_id: UUID,
        *,
        deleted_at: datetime | None = None,
    ) -> ProjectionT | None:
        await cls.bulk_tombstone_projections(
            db,
            model,
            [entity_id],
            deleted_at=deleted_at,
        )
        return await db.get(model, entity_id)

    @staticmethod
    async def mark_all_projection_rows_deleted(
        db: AsyncSession,
        *,
        deleted_at: datetime | None = None,
    ) -> None:
        timestamp = deleted_at or datetime.now(UTC)
        for model in PROJECTION_MODELS:
            await db.execute(
                update(model).values(
                    source_deleted_at=timestamp,
                    updated_at=func.now(),
                )
            )

    @staticmethod
    async def _get_by_id(
        db: AsyncSession,
        model: type[ProjectionT],
        entity_id: UUID,
        *,
        lock: bool = False,
        include_deleted: bool = False,
    ) -> ProjectionT | None:
        query = select(model).where(model.id == entity_id)
        if not include_deleted and hasattr(model, "source_deleted_at"):
            query = query.where(model.source_deleted_at.is_(None))
        if lock:
            query = query.with_for_update(of=model)
        return (await db.execute(query)).scalar_one_or_none()

    @classmethod
    async def get_session_by_id(
        cls, db: AsyncSession, session_id: UUID, *, lock: bool = False
    ) -> AcademicSession | None:
        return await cls._get_by_id(db, AcademicSession, session_id, lock=lock)

    @staticmethod
    async def get_current_session(
        db: AsyncSession, *, lock: bool = False
    ) -> AcademicSession | None:
        query = select(AcademicSession).where(
            AcademicSession.is_current.is_(True),
            AcademicSession.source_deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update(of=AcademicSession)
        return (await db.execute(query)).scalar_one_or_none()

    @classmethod
    async def get_term_by_id(
        cls, db: AsyncSession, term_id: UUID, *, lock: bool = False
    ) -> AcademicTerm | None:
        return await cls._get_by_id(db, AcademicTerm, term_id, lock=lock)

    @staticmethod
    async def get_current_term(
        db: AsyncSession, *, session_id: UUID | None = None
    ) -> AcademicTerm | None:
        query = select(AcademicTerm).where(
            AcademicTerm.is_current.is_(True),
            AcademicTerm.source_deleted_at.is_(None),
        )
        if session_id is not None:
            query = query.where(AcademicTerm.academic_session_id == session_id)
        return (await db.execute(query)).scalar_one_or_none()

    @classmethod
    async def get_level_by_id(
        cls, db: AsyncSession, level_id: UUID, *, lock: bool = False
    ) -> AcademicLevel | None:
        return await cls._get_by_id(db, AcademicLevel, level_id, lock=lock)

    @staticmethod
    async def list_levels(db: AsyncSession) -> list[AcademicLevel]:
        result = await db.execute(
            select(AcademicLevel)
            .where(AcademicLevel.source_deleted_at.is_(None))
            .order_by(
                AcademicLevel.category.asc(),
                AcademicLevel.position.asc(),
                AcademicLevel.name.asc(),
            )
        )
        return list(result.scalars().all())

    @classmethod
    async def get_arm_label_by_id(
        cls, db: AsyncSession, arm_label_id: UUID
    ) -> ArmLabel | None:
        return await cls._get_by_id(db, ArmLabel, arm_label_id)

    @classmethod
    async def get_department_by_id(
        cls, db: AsyncSession, department_id: UUID
    ) -> Department | None:
        return await cls._get_by_id(db, Department, department_id)

    @classmethod
    async def get_class_by_id(
        cls, db: AsyncSession, class_id: UUID, *, lock: bool = False
    ) -> AcademicClass | None:
        return await cls._get_by_id(db, AcademicClass, class_id, lock=lock)

    @staticmethod
    async def list_classes_for_level(
        db: AsyncSession,
        academic_level_id: UUID,
        *,
        active_only: bool = True,
    ) -> list[AcademicClass]:
        query = select(AcademicClass).where(
            AcademicClass.academic_level_id == academic_level_id,
            AcademicClass.source_deleted_at.is_(None),
        )
        if active_only:
            query = query.where(AcademicClass.is_active.is_(True))
        result = await db.execute(query.order_by(AcademicClass.display_name.asc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_class_term_department(
        db: AsyncSession,
        class_id: UUID,
        academic_term_id: UUID,
    ) -> ClassTermDepartment | None:
        return (
            await db.execute(
                select(ClassTermDepartment).where(
                    ClassTermDepartment.class_id == class_id,
                    ClassTermDepartment.academic_term_id == academic_term_id,
                    ClassTermDepartment.source_deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    @classmethod
    async def get_subject_by_id(
        cls, db: AsyncSession, subject_id: UUID
    ) -> AcademicSubject | None:
        return await cls._get_by_id(db, AcademicSubject, subject_id)

    @staticmethod
    async def list_subjects_by_ids(
        db: AsyncSession, subject_ids: Sequence[UUID]
    ) -> list[AcademicSubject]:
        unique_ids = set(subject_ids)

        if not unique_ids:
            return []

        result = await db.execute(
            select(AcademicSubject)
            .where(
                AcademicSubject.id.in_(unique_ids),
                AcademicSubject.source_deleted_at.is_(None),
            )
            .order_by(AcademicSubject.name.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def get_curriculum_by_id(
        cls, db: AsyncSession, curriculum_id: UUID
    ) -> Curriculum | None:
        return await cls._get_by_id(db, Curriculum, curriculum_id)

    @staticmethod
    async def get_curriculum_for_level(
        db: AsyncSession, academic_level_id: UUID
    ) -> Curriculum | None:
        return (
            await db.execute(
                select(Curriculum).where(
                    Curriculum.academic_level_id == academic_level_id,
                    Curriculum.source_deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    @classmethod
    async def get_curriculum_subject_by_id(
        cls,
        db: AsyncSession,
        curriculum_subject_id: UUID,
        *,
        lock: bool = False,
    ) -> CurriculumSubject | None:
        return await cls._get_by_id(
            db, CurriculumSubject, curriculum_subject_id, lock=lock
        )

    @staticmethod
    async def list_curriculum_subjects(
        db: AsyncSession,
        curriculum_id: UUID,
        *,
        active_only: bool = True,
    ) -> list[CurriculumSubject]:
        query = select(CurriculumSubject).where(
            CurriculumSubject.curriculum_id == curriculum_id,
            CurriculumSubject.source_deleted_at.is_(None),
        )
        if active_only:
            query = query.where(CurriculumSubject.is_active.is_(True))
        return list(
            (await db.execute(query.order_by(CurriculumSubject.subject_id.asc())))
            .scalars()
            .all()
        )

    @classmethod
    async def get_curriculum_subject_department_by_id(
        cls,
        db: AsyncSession,
        link_id: UUID,
    ) -> CurriculumSubjectDepartment | None:
        return await cls._get_by_id(db, CurriculumSubjectDepartment, link_id)

    @staticmethod
    async def list_curriculum_subject_departments(
        db: AsyncSession,
        curriculum_subject_id: UUID,
    ) -> list[CurriculumSubjectDepartment]:
        result = await db.execute(
            select(CurriculumSubjectDepartment)
            .where(
                CurriculumSubjectDepartment.curriculum_subject_id
                == curriculum_subject_id,
                CurriculumSubjectDepartment.source_deleted_at.is_(None),
            )
            .order_by(CurriculumSubjectDepartment.department_id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_curriculum_subject_department_for_scope(
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID,
        department_id: UUID,
    ) -> CurriculumSubjectDepartment | None:
        return (
            await db.execute(
                select(CurriculumSubjectDepartment).where(
                    CurriculumSubjectDepartment.curriculum_subject_id
                    == curriculum_subject_id,
                    CurriculumSubjectDepartment.department_id == department_id,
                    CurriculumSubjectDepartment.source_deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def curriculum_subject_has_department_scope(
        db: AsyncSession,
        curriculum_subject_id: UUID,
    ) -> bool:
        return bool(
            await db.scalar(
                select(
                    exists().where(
                        CurriculumSubjectDepartment.curriculum_subject_id
                        == curriculum_subject_id,
                        CurriculumSubjectDepartment.source_deleted_at.is_(None),
                    )
                )
            )
        )

    @classmethod
    async def get_assessment_scheme_by_id(
        cls, db: AsyncSession, scheme_id: UUID
    ) -> AssessmentScheme | None:
        return await cls._get_by_id(db, AssessmentScheme, scheme_id)

    @classmethod
    async def get_component_by_id(
        cls, db: AsyncSession, component_id: UUID
    ) -> AssessmentComponent | None:
        return await cls._get_by_id(db, AssessmentComponent, component_id)

    @classmethod
    async def get_admin_by_id(
        cls, db: AsyncSession, admin_id: UUID
    ) -> AcademicAdmin | None:
        return await cls._get_by_id(db, AcademicAdmin, admin_id)

    @classmethod
    async def get_teacher_by_id(
        cls, db: AsyncSession, teacher_id: UUID
    ) -> AcademicTeacher | None:
        return await cls._get_by_id(db, AcademicTeacher, teacher_id)

    @staticmethod
    async def list_teachers(
        db: AsyncSession,
        *,
        active_only: bool = True,
    ) -> list[AcademicTeacher]:
        query = select(AcademicTeacher).where(
            AcademicTeacher.source_deleted_at.is_(None)
        )
        if active_only:
            query = query.where(AcademicTeacher.status == "active")
        result = await db.execute(
            query.order_by(
                AcademicTeacher.last_name.asc(),
                AcademicTeacher.first_name.asc(),
                AcademicTeacher.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_teachers_by_ids(
        db: AsyncSession,
        teacher_ids: Sequence[UUID],
        *,
        active_only: bool = True,
    ) -> list[AcademicTeacher]:
        unique_ids = list(dict.fromkeys(teacher_ids))
        if not unique_ids:
            return []
        query = select(AcademicTeacher).where(
            AcademicTeacher.id.in_(unique_ids),
            AcademicTeacher.source_deleted_at.is_(None),
        )
        if active_only:
            query = query.where(AcademicTeacher.status == "active")
        result = await db.execute(query.order_by(AcademicTeacher.id.asc()))
        return list(result.scalars().all())

    @classmethod
    async def get_teacher_by_membership_id(
        cls,
        db: AsyncSession,
        membership_id: UUID | str,
    ) -> AcademicTeacher | None:
        try:
            teacher_id = (
                membership_id
                if isinstance(membership_id, UUID)
                else UUID(membership_id)
            )
        except (TypeError, ValueError):
            return None
        return await cls.get_teacher_by_id(db, teacher_id)

    @classmethod
    async def get_assignment_by_id(
        cls, db: AsyncSession, assignment_id: UUID
    ) -> TeacherAssignment | None:
        return await cls._get_by_id(db, TeacherAssignment, assignment_id)

    @staticmethod
    async def list_effective_teacher_assignments(
        db: AsyncSession, *, teacher_membership_id: UUID | None = None
    ) -> list[TeacherAssignment]:
        query = select(TeacherAssignment).where(
            TeacherAssignment.source_deleted_at.is_(None),
            *AcademicRepository._effective_assignment_predicates(),
        )

        if teacher_membership_id is not None:
            query = query.where(
                TeacherAssignment.teacher_membership_id == teacher_membership_id
            )

        result = await db.execute(
            query.order_by(
                TeacherAssignment.class_id.asc(),
                TeacherAssignment.curriculum_subject_id.asc(),
                TeacherAssignment.teacher_membership_id.asc(),
            )
        )

        return list(result.scalars().all())

    @staticmethod
    async def list_classes_by_ids(
        db: AsyncSession, class_ids: Sequence[UUID]
    ) -> list[AcademicClass]:
        unique_ids = set(class_ids)

        if not unique_ids:
            return []

        result = await db.execute(
            select(AcademicClass)
            .where(
                AcademicClass.id.in_(unique_ids),
                AcademicClass.source_deleted_at.is_(None),
            )
            .order_by(AcademicClass.display_name.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_curriculum_subjects_by_ids(
        db: AsyncSession, curriculum_subject_ids: Sequence[UUID]
    ) -> list[CurriculumSubject]:
        unique_ids = set(curriculum_subject_ids)

        if not unique_ids:
            return []

        result = await db.execute(
            select(CurriculumSubject)
            .where(
                CurriculumSubject.id.in_(unique_ids),
                CurriculumSubject.source_deleted_at.is_(None),
            )
            .order_by(CurriculumSubject.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    def _effective_assignment_predicates() -> tuple[Any, Any]:
        today = datetime.now(UTC).date()
        return (
            TeacherAssignment.effective_from <= today,
            or_(
                TeacherAssignment.effective_to.is_(None),
                TeacherAssignment.effective_to >= today,
            ),
        )

    @staticmethod
    async def get_active_assignment_for_scope(
        db: AsyncSession,
        *,
        teacher_membership_id: UUID,
        class_id: UUID,
        curriculum_subject_id: UUID,
    ) -> TeacherAssignment | None:
        return (
            await db.execute(
                select(TeacherAssignment).where(
                    TeacherAssignment.teacher_membership_id == teacher_membership_id,
                    TeacherAssignment.class_id == class_id,
                    TeacherAssignment.curriculum_subject_id == curriculum_subject_id,
                    TeacherAssignment.source_deleted_at.is_(None),
                    *AcademicRepository._effective_assignment_predicates(),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_active_assignment_for_class_curriculum_subject(
        db: AsyncSession,
        class_id: UUID,
        curriculum_subject_id: UUID,
    ) -> TeacherAssignment | None:
        return (
            await db.execute(
                select(TeacherAssignment).where(
                    TeacherAssignment.class_id == class_id,
                    TeacherAssignment.curriculum_subject_id == curriculum_subject_id,
                    TeacherAssignment.source_deleted_at.is_(None),
                    *AcademicRepository._effective_assignment_predicates(),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def teacher_has_curriculum_subject_assignment(
        db: AsyncSession,
        teacher_membership_id: UUID,
        curriculum_subject_id: UUID,
    ) -> bool:
        return bool(
            await db.scalar(
                select(
                    exists().where(
                        TeacherAssignment.teacher_membership_id
                        == teacher_membership_id,
                        TeacherAssignment.curriculum_subject_id
                        == curriculum_subject_id,
                        TeacherAssignment.source_deleted_at.is_(None),
                        *AcademicRepository._effective_assignment_predicates(),
                    )
                )
            )
        )

    @classmethod
    async def get_enrollment_by_id(
        cls, db: AsyncSession, enrollment_id: UUID
    ) -> StudentEnrollment | None:
        return await cls._get_by_id(db, StudentEnrollment, enrollment_id)

    @staticmethod
    async def list_current_enrollments_for_class(
        db: AsyncSession,
        class_id: UUID,
        *,
        academic_session_id: UUID | None = None,
    ) -> list[StudentEnrollment]:
        query = select(StudentEnrollment).where(
            StudentEnrollment.class_id == class_id,
            StudentEnrollment.is_current.is_(True),
            StudentEnrollment.student_status == "active",
            StudentEnrollment.source_deleted_at.is_(None),
        )
        if academic_session_id is not None:
            query = query.where(
                StudentEnrollment.academic_session_id == academic_session_id
            )
        result = await db.execute(
            query.order_by(StudentEnrollment.admission_number.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_current_enrollments_for_classes(
        db: AsyncSession,
        class_ids: Sequence[UUID],
        *,
        academic_session_id: UUID | None = None,
    ) -> list[StudentEnrollment]:
        unique_class_ids = tuple(dict.fromkeys(class_ids))
        if not unique_class_ids:
            return []
        query = select(StudentEnrollment).where(
            StudentEnrollment.class_id.in_(unique_class_ids),
            StudentEnrollment.is_current.is_(True),
            StudentEnrollment.student_status == "active",
            StudentEnrollment.source_deleted_at.is_(None),
        )
        if academic_session_id is not None:
            query = query.where(
                StudentEnrollment.academic_session_id == academic_session_id
            )
        result = await db.execute(
            query.order_by(
                StudentEnrollment.class_id.asc(),
                StudentEnrollment.admission_number.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_all_active_curriculum_subjects(
        db: AsyncSession,
    ) -> list[CurriculumSubject]:
        """Return all live active CurriculumSubjects available to CBT."""

        result = await db.execute(
            select(CurriculumSubject)
            .where(
                CurriculumSubject.is_active.is_(True),
                CurriculumSubject.source_deleted_at.is_(None),
            )
            .order_by(CurriculumSubject.subject_id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_authorable_curriculum_subjects_for_teacher(
        db: AsyncSession,
        *,
        teacher_membership_id: UUID,
    ) -> list[CurriculumSubject]:
        """Return every subject with a current effective teacher assignment."""

        query = (
            select(CurriculumSubject)
            .join(
                TeacherAssignment,
                TeacherAssignment.curriculum_subject_id == CurriculumSubject.id,
            )
            .where(
                TeacherAssignment.teacher_membership_id == teacher_membership_id,
                TeacherAssignment.source_deleted_at.is_(None),
                CurriculumSubject.is_active.is_(True),
                CurriculumSubject.source_deleted_at.is_(None),
                *AcademicRepository._effective_assignment_predicates(),
            )
            .distinct()
            .order_by(CurriculumSubject.subject_id.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def list_teacher_classes_for_curriculum_subject(
        db: AsyncSession,
        *,
        teacher_membership_id: UUID,
        curriculum_subject_id: UUID,
    ) -> list[AcademicClass]:
        """Return classes for which the teacher has a current assignment."""

        query = (
            select(AcademicClass)
            .join(
                TeacherAssignment,
                TeacherAssignment.class_id == AcademicClass.id,
            )
            .where(
                TeacherAssignment.teacher_membership_id == teacher_membership_id,
                TeacherAssignment.curriculum_subject_id == curriculum_subject_id,
                TeacherAssignment.source_deleted_at.is_(None),
                AcademicClass.is_active.is_(True),
                AcademicClass.source_deleted_at.is_(None),
                *AcademicRepository._effective_assignment_predicates(),
            )
            .distinct()
            .order_by(AcademicClass.display_name.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def list_classes_for_curriculum_subject(
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID,
    ) -> list[AcademicClass]:
        """Return all live classes in the subject's academic level.

        This is intentionally a structural query only. Department/term
        applicability is a business rule and is resolved by the academic service.
        """

        query = (
            select(AcademicClass)
            .join(
                Curriculum,
                Curriculum.academic_level_id == AcademicClass.academic_level_id,
            )
            .join(
                CurriculumSubject,
                CurriculumSubject.curriculum_id == Curriculum.id,
            )
            .where(
                CurriculumSubject.id == curriculum_subject_id,
                CurriculumSubject.is_active.is_(True),
                CurriculumSubject.source_deleted_at.is_(None),
                Curriculum.source_deleted_at.is_(None),
                AcademicClass.is_active.is_(True),
                AcademicClass.source_deleted_at.is_(None),
            )
            .order_by(AcademicClass.display_name.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())
