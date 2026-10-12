"""Academic curriculum and specialization resolution.

This service interprets the synchronized Weave academic projection.
It does not mutate academic data; Weave remains the source of truth.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicScopeError
from app.domains.academics.models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    Curriculum,
    CurriculumSubject,
)
from app.domains.academics.repository import AcademicRepository

TERM_POSITIONS: dict[str, int] = {
    "first_term": 1,
    "second_term": 2,
    "third_term": 3,
}


class AcademicEligibilityService:
    """Resolve class/term curriculum eligibility from local Weave projections."""

    @staticmethod
    def term_position(term: AcademicTerm) -> int:
        """Return Weave's numeric position for a synchronized academic term."""

        raw_name = getattr(term.name, "value", term.name)
        position = TERM_POSITIONS.get(str(raw_name))
        if position is None:
            raise AcademicScopeError(
                f"Unsupported academic term name '{raw_name}' "
                "in the local academic projection"
            )
        return position

    @classmethod
    def specialization_is_active(
        cls,
        level: AcademicLevel,
        term: AcademicTerm,
    ) -> bool:
        """Return whether specialization rules apply for this level and term."""

        threshold = level.specialization_required_from_term_position
        if threshold is None:
            return False
        return cls.term_position(term) >= threshold

    @staticmethod
    async def _require_term(
        db: AsyncSession,
        academic_term_id: UUID,
    ) -> AcademicTerm:
        term = await AcademicRepository.get_term_by_id(db, academic_term_id)
        if term is None:
            raise AcademicScopeError(
                "Academic term does not exist or is no longer available"
            )
        return term

    @staticmethod
    async def _require_class(
        db: AsyncSession,
        class_id: UUID,
    ) -> AcademicClass:
        classroom = await AcademicRepository.get_class_by_id(db, class_id)
        if classroom is None:
            raise AcademicScopeError("Class does not exist or is no longer available")
        if not classroom.is_active:
            raise AcademicScopeError("Class is inactive")
        return classroom

    @staticmethod
    async def _require_curriculum_subject(
        db: AsyncSession,
        curriculum_subject_id: UUID,
    ) -> CurriculumSubject:
        curriculum_subject = await AcademicRepository.get_curriculum_subject_by_id(
            db,
            curriculum_subject_id,
        )
        if curriculum_subject is None:
            raise AcademicScopeError(
                "Curriculum subject does not exist or is no longer available"
            )
        if not curriculum_subject.is_active:
            raise AcademicScopeError("Curriculum subject is inactive")
        return curriculum_subject

    @staticmethod
    async def _require_curriculum(
        db: AsyncSession,
        curriculum_id: UUID,
    ) -> Curriculum:
        curriculum = await AcademicRepository.get_curriculum_by_id(db, curriculum_id)
        if curriculum is None:
            raise AcademicScopeError(
                "Curriculum does not exist or is no longer available"
            )
        return curriculum

    @staticmethod
    async def _require_level(
        db: AsyncSession,
        academic_level_id: UUID,
    ) -> AcademicLevel:
        level = await AcademicRepository.get_level_by_id(db, academic_level_id)
        if level is None:
            raise AcademicScopeError(
                "Academic level does not exist or is no longer available"
            )
        return level

    @classmethod
    async def subject_applies_to_class(
        cls,
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID,
        class_id: UUID,
        academic_term_id: UUID,
    ) -> bool:
        """Return whether a curriculum subject applies to one class for one term."""

        term = await cls._require_term(db, academic_term_id)
        classroom = await cls._require_class(db, class_id)
        curriculum_subject = await cls._require_curriculum_subject(
            db,
            curriculum_subject_id,
        )
        curriculum = await cls._require_curriculum(
            db,
            curriculum_subject.curriculum_id,
        )

        if classroom.academic_level_id != curriculum.academic_level_id:
            return False

        level = await cls._require_level(db, curriculum.academic_level_id)
        if not cls.specialization_is_active(level, term):
            return True

        class_department = await AcademicRepository.get_class_term_department(
            db,
            class_id,
            academic_term_id,
        )
        if class_department is None:
            raise AcademicScopeError(
                "Class requires a department specialization for the selected academic term"
            )

        department_links = await AcademicRepository.list_curriculum_subject_departments(
            db,
            curriculum_subject_id,
        )
        if not department_links:
            return True

        allowed_department_ids = {link.department_id for link in department_links}
        return class_department.department_id in allowed_department_ids

    @classmethod
    async def list_eligible_classes(
        cls,
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID,
        academic_term_id: UUID,
    ) -> list[AcademicClass]:
        """Return all active classes eligible for a curriculum subject in a term."""

        term = await cls._require_term(db, academic_term_id)
        curriculum_subject = await cls._require_curriculum_subject(
            db,
            curriculum_subject_id,
        )
        curriculum = await cls._require_curriculum(
            db,
            curriculum_subject.curriculum_id,
        )
        level = await cls._require_level(db, curriculum.academic_level_id)

        classes = await AcademicRepository.list_classes_for_level(
            db,
            curriculum.academic_level_id,
            active_only=True,
        )
        if not classes:
            return []

        if not cls.specialization_is_active(level, term):
            return classes

        department_links = await AcademicRepository.list_curriculum_subject_departments(
            db,
            curriculum_subject_id,
        )
        allowed_department_ids = {link.department_id for link in department_links}
        subject_is_general = not allowed_department_ids

        eligible_classes: list[AcademicClass] = []
        for classroom in classes:
            class_department = await AcademicRepository.get_class_term_department(
                db,
                classroom.id,
                academic_term_id,
            )
            if class_department is None:
                raise AcademicScopeError(
                    f"Class '{classroom.display_name}' requires a department "
                    "specialization for the selected academic term"
                )

            if (
                subject_is_general
                or class_department.department_id in allowed_department_ids
            ):
                eligible_classes.append(classroom)

        return eligible_classes
