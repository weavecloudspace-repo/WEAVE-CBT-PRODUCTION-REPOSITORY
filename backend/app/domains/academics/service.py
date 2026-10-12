"""Read-oriented academic query services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.academics.authorization import AcademicAuthorizationService
from app.domains.academics.eligibility import AcademicEligibilityService
from app.domains.academics.query_repository import AcademicQueryRepository
from app.domains.academics.repository import AcademicRepository
from app.domains.academics.schemas import (
    AssessmentComponentResponse,
    AssessmentSchemeResponse,
    AuthorableCurriculumSubjectResponse,
    EligibleAcademicClassResponse,
    TeacherAssignmentResponse,
)
from app.domains.auth.models import LocalActor


class AcademicQueryService:
    """Read-oriented operations over synchronized academic projections"""

    @staticmethod
    async def list_authorable_curriculum_subjects(
        db: AsyncSession,
        *,
        actor: LocalActor,
    ) -> list[AuthorableCurriculumSubjectResponse]:
        curriculum_subjects = await AcademicAuthorizationService.list_actor_authorable_curriculum_subjects(
            db,
            actor=actor,
        )

        if not curriculum_subjects:
            return []

        subjects = await AcademicRepository.list_subjects_by_ids(
            db,
            subject_ids=[
                curriculum_subject.subject_id
                for curriculum_subject in curriculum_subjects
            ],
        )
        subjects_by_id = {subject.id: subject for subject in subjects}

        curriculum_ids = list(
            dict.fromkeys(
                curriculum_subject.curriculum_id
                for curriculum_subject in curriculum_subjects
            )
        )
        curricula_by_id = {}
        for curriculum_id in curriculum_ids:
            curriculum = await AcademicRepository.get_curriculum_by_id(
                db,
                curriculum_id,
            )
            if curriculum is None:
                raise AcademicScopeError(
                    "Curriculum subject references an unavailable curriculum"
                )
            curricula_by_id[curriculum.id] = curriculum

        levels = await AcademicRepository.list_levels(db)
        levels_by_id = {level.id: level for level in levels}
        level_order = {level.id: index for index, level in enumerate(levels)}

        response: list[AuthorableCurriculumSubjectResponse] = []
        for curriculum_subject in curriculum_subjects:
            subject = subjects_by_id.get(curriculum_subject.subject_id)
            if subject is None:
                raise AcademicScopeError(
                    "Curriculum subject references an unavailable academic subject"
                )

            curriculum = curricula_by_id.get(curriculum_subject.curriculum_id)
            if curriculum is None:
                raise AcademicScopeError(
                    "Curriculum subject references an unavailable curriculum"
                )

            level = levels_by_id.get(curriculum.academic_level_id)
            if level is None:
                raise AcademicScopeError(
                    "Curriculum references an unavailable academic level"
                )

            response.append(
                AuthorableCurriculumSubjectResponse(
                    id=curriculum_subject.id,
                    curriculum_id=curriculum_subject.curriculum_id,
                    academic_level_id=level.id,
                    academic_level_name=level.name,
                    academic_level_category=level.category,
                    academic_level_position=level.position,
                    subject_id=subject.id,
                    subject_name=subject.name,
                    subject_code=subject.code,
                    is_elective=curriculum_subject.is_elective,
                    is_active=curriculum_subject.is_active,
                )
            )

        response.sort(
            key=lambda item: (
                level_order.get(item.academic_level_id, len(level_order)),
                item.subject_name.casefold(),
                item.subject_code or "",
            )
        )
        return response

    @staticmethod
    async def list_effective_teacher_assignments(
        db: AsyncSession,
        *,
        actor: LocalActor,
    ) -> list[TeacherAssignmentResponse]:
        assignments = (
            await AcademicAuthorizationService.list_actor_effective_teacher_assignments(
                db,
                actor=actor,
            )
        )

        if not assignments:
            return []

        teachers = await AcademicRepository.list_teachers_by_ids(
            db,
            [assignment.teacher_membership_id for assignment in assignments],
            active_only=False,
        )

        classes = await AcademicRepository.list_classes_by_ids(
            db,
            [assignment.class_id for assignment in assignments],
        )

        curriculum_subjects = await AcademicRepository.list_curriculum_subjects_by_ids(
            db,
            [assignment.curriculum_subject_id for assignment in assignments],
        )

        subjects = await AcademicRepository.list_subjects_by_ids(
            db,
            [
                curriculum_subject.subject_id
                for curriculum_subject in curriculum_subjects
            ],
        )

        teachers_by_id = {teacher.id: teacher for teacher in teachers}
        classes_by_id = {classroom.id: classroom for classroom in classes}
        curriculum_subjects_by_id = {
            curriculum_subject.id: curriculum_subject
            for curriculum_subject in curriculum_subjects
        }
        subjects_by_id = {subject.id: subject for subject in subjects}

        response: list[TeacherAssignmentResponse] = []

        for assignment in assignments:
            teacher = teachers_by_id.get(assignment.teacher_membership_id)
            classroom = classes_by_id.get(assignment.class_id)
            curriculum_subject = curriculum_subjects_by_id.get(
                assignment.curriculum_subject_id
            )

            if teacher is None:
                raise AcademicScopeError(
                    "Teacher assignment references an unavailable teacher"
                )

            if classroom is None:
                raise AcademicScopeError(
                    "Teacher assignment references an unavailable class"
                )

            if curriculum_subject is None:
                raise AcademicScopeError(
                    "Teacher assignment references an unavailable curriculum subject"
                )

            subject = subjects_by_id.get(curriculum_subject.subject_id)

            if subject is None:
                raise AcademicScopeError(
                    "Curriculum subject references an unavailable academic subject"
                )

            teacher_name = " ".join(
                part
                for part in (
                    teacher.first_name,
                    teacher.last_name,
                )
                if part
            ).strip()

            if not teacher_name:
                teacher_name = teacher.staff_id or "Unnamed teacher"

            response.append(
                TeacherAssignmentResponse(
                    id=assignment.id,
                    teacher_membership_id=assignment.teacher_membership_id,
                    teacher_name=teacher_name,
                    class_id=assignment.class_id,
                    class_name=classroom.display_name,
                    curriculum_subject_id=assignment.curriculum_subject_id,
                    subject_id=subject.id,
                    subject_name=subject.name,
                    subject_code=subject.code,
                    effective_from=assignment.effective_from,
                    effective_to=assignment.effective_to,
                )
            )

        return response

    @staticmethod
    async def list_eligible_classes_for_curriculum_subject(
        db: AsyncSession,
        *,
        actor: LocalActor,
        curriculum_subject_id: UUID,
        academic_term_id: UUID,
    ) -> list[EligibleAcademicClassResponse]:
        await (
            AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=curriculum_subject_id,
                academic_term_id=academic_term_id,
            )
        )

        classes = await AcademicEligibilityService.list_eligible_classes(
            db,
            curriculum_subject_id=curriculum_subject_id,
            academic_term_id=academic_term_id,
        )

        return [
            EligibleAcademicClassResponse.model_validate(classroom)
            for classroom in classes
        ]

    @staticmethod
    async def list_assessment_schemes(
        db: AsyncSession,
        *,
        actor: LocalActor,
        active_only: bool = True,
    ) -> list[AssessmentSchemeResponse]:
        if not actor.is_active or actor.role not in {"admin", "teacher"}:
            raise AcademicAuthorizationError(
                "Only active administrators and teachers can read assessment metadata"
            )

        schemes = await AcademicQueryRepository.list_assessment_schemes(
            db,
            active_only=active_only,
        )
        return [AssessmentSchemeResponse.model_validate(scheme) for scheme in schemes]

    @staticmethod
    async def list_assessment_components(
        db: AsyncSession,
        *,
        actor: LocalActor,
        assessment_scheme_id: UUID,
        active_only: bool = True,
    ) -> list[AssessmentComponentResponse]:
        if not actor.is_active or actor.role not in {"admin", "teacher"}:
            raise AcademicAuthorizationError(
                "Only active administrators and teachers can read assessment metadata"
            )

        scheme = await AcademicRepository.get_assessment_scheme_by_id(
            db,
            scheme_id=assessment_scheme_id,
        )
        if scheme is None:
            raise AcademicScopeError(
                "Assessment scheme does not exist or is no longer available"
            )

        components = await AcademicQueryRepository.list_assessment_components(
            db,
            assessment_scheme_id=assessment_scheme_id,
            active_only=active_only,
        )
        return [
            AssessmentComponentResponse.model_validate(component)
            for component in components
        ]
