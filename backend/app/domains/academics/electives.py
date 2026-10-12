"""Student elective eligibility derived from authoritative Weave projections.

Weave owns elective choice. CBT stores only the minimal read-only projection
needed to build local exam audiences while remaining offline during execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.models import (
    CurriculumSubject,
    StudentElectiveSelection,
    StudentEnrollment,
)
from app.domains.academics.repository import AcademicRepository


class ElectiveProjectionRepository:
    """Persistence helpers specific to elective projection rows."""

    @staticmethod
    async def mark_all_deleted(
        db: AsyncSession,
        *,
        deleted_at: datetime | None = None,
    ) -> None:
        timestamp = deleted_at or datetime.now(UTC)
        await db.execute(
            update(StudentElectiveSelection).values(
                source_deleted_at=timestamp,
                updated_at=func.now(),
            )
        )

    @staticmethod
    async def selected_student_ids(
        db: AsyncSession,
        *,
        curriculum_subject: CurriculumSubject,
        student_ids: Sequence[UUID] | None = None,
    ) -> set[UUID]:
        """Return live selected students for one grouped elective subject.

        Matching both subject and group prevents a malformed/stale selection row
        from granting eligibility after a curriculum subject changes groups.
        """

        if (
            not curriculum_subject.is_elective
            or curriculum_subject.elective_group_id is None
        ):
            return set(student_ids or ())

        query = select(StudentElectiveSelection.student_id).where(
            StudentElectiveSelection.curriculum_subject_id == curriculum_subject.id,
            StudentElectiveSelection.elective_group_id
            == curriculum_subject.elective_group_id,
            StudentElectiveSelection.source_deleted_at.is_(None),
        )
        if student_ids is not None:
            unique_ids = tuple(dict.fromkeys(student_ids))
            if not unique_ids:
                return set()
            query = query.where(StudentElectiveSelection.student_id.in_(unique_ids))
        result = await db.execute(query)
        return set(result.scalars().all())


class ElectiveEligibilityService:
    """Apply Weave elective choice to pre-execution CBT audiences."""

    @staticmethod
    def is_grouped_elective(curriculum_subject: CurriculumSubject) -> bool:
        return bool(
            curriculum_subject.is_elective
            and curriculum_subject.elective_group_id is not None
        )

    @classmethod
    async def filter_enrollments(
        cls,
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID,
        enrollments: Sequence[StudentEnrollment],
    ) -> list[StudentEnrollment]:
        """Filter class-eligible enrollments through current elective choice.

        Compulsory subjects and legacy ungrouped electives preserve the existing
        class-level behavior. Grouped electives require an exact live Weave
        selection. This function is used only before execution; frozen candidate
        and attempt evidence is never rewritten after an exam starts.
        """

        subject = await AcademicRepository.get_curriculum_subject_by_id(
            db,
            curriculum_subject_id,
        )
        if subject is None or not subject.is_active:
            return []
        if not cls.is_grouped_elective(subject):
            return list(enrollments)

        selected_ids = await ElectiveProjectionRepository.selected_student_ids(
            db,
            curriculum_subject=subject,
            student_ids=[enrollment.student_id for enrollment in enrollments],
        )
        return [
            enrollment
            for enrollment in enrollments
            if enrollment.student_id in selected_ids
        ]

    @classmethod
    async def projected_student_ids_for_classes(
        cls,
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID,
        class_ids: Sequence[UUID],
        academic_session_id: UUID,
    ) -> set[UUID]:
        enrollments = await AcademicRepository.list_current_enrollments_for_classes(
            db,
            class_ids,
            academic_session_id=academic_session_id,
        )
        filtered = await cls.filter_enrollments(
            db,
            curriculum_subject_id=curriculum_subject_id,
            enrollments=enrollments,
        )
        return {enrollment.student_id for enrollment in filtered}

    @classmethod
    async def subject_requires_selection(
        cls,
        db: AsyncSession,
        curriculum_subject_id: UUID,
    ) -> bool:
        subject = await AcademicRepository.get_curriculum_subject_by_id(
            db,
            curriculum_subject_id,
        )
        return bool(subject and subject.is_active and cls.is_grouped_elective(subject))
