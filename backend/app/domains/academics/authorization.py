# ==================================================#
# backend.app.domains.academics.authorization.py
# ==================================================#

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.academics.eligibility import AcademicEligibilityService
from app.domains.academics.models import CurriculumSubject, TeacherAssignment
from app.domains.academics.repository import AcademicRepository
from app.domains.auth.models import LocalActor


class AcademicAuthorizationService:
    """Authorization rules backed by synchronized local academic projections."""

    @staticmethod
    async def require_can_author_curriculum_subject(
        db: AsyncSession,
        *,
        actor: LocalActor,
        curriculum_subject_id: UUID,
    ) -> None:
        """Require general authoring access to one live CurriculumSubject."""

        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")

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

        if actor.role == "admin":
            return

        if actor.role != "teacher":
            raise AcademicAuthorizationError(
                "Only administrators and teachers can author academic content"
            )

        teacher_membership_id = AcademicAuthorizationService._teacher_membership_id(
            actor
        )

        await AcademicAuthorizationService._require_live_teacher(
            db,
            teacher_membership_id=teacher_membership_id,
        )

        assigned_classes = (
            await AcademicRepository.list_teacher_classes_for_curriculum_subject(
                db,
                teacher_membership_id=teacher_membership_id,
                curriculum_subject_id=curriculum_subject_id,
            )
        )

        if not assigned_classes:
            raise AcademicAuthorizationError(
                "Teacher does not have an active assignment in a live class for this curriculum subject"
            )

    @classmethod
    async def require_can_author_curriculum_subject_for_term(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        curriculum_subject_id: UUID,
        academic_term_id: UUID,
    ) -> None:
        """Require permission to help author a level-wide subject exam for one term.

        An exam is not owned by one class. AcademicEligibilityService determines the
        full set of classes that may take the subject in the selected term.

        Administrators may author when the subject has at least one academically
        eligible class for the term.

        A teacher may participate in joint authoring when they hold a current
        assignment for the subject in at least one of those academically eligible
        classes. Their personal assignment does not reduce the exam audience.
        """

        await cls.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=curriculum_subject_id,
        )

        eligible_classes = await AcademicEligibilityService.list_eligible_classes(
            db,
            curriculum_subject_id=curriculum_subject_id,
            academic_term_id=academic_term_id,
        )

        if not eligible_classes:
            raise AcademicScopeError(
                "Curriculum subject has no academically eligible classes "
                "for the selected academic term"
            )

        if actor.role == "admin":
            return

        teacher_membership_id = cls._teacher_membership_id(actor)
        assigned_classes = (
            await AcademicRepository.list_teacher_classes_for_curriculum_subject(
                db,
                teacher_membership_id=teacher_membership_id,
                curriculum_subject_id=curriculum_subject_id,
            )
        )

        eligible_class_ids = {classroom.id for classroom in eligible_classes}
        if not any(
            classroom.id in eligible_class_ids for classroom in assigned_classes
        ):
            raise AcademicAuthorizationError(
                "Teacher does not have an active assignment in any academically "
                "eligible class for this curriculum subject and term"
            )

    @staticmethod
    async def require_teacher_assignment_for_class(
        db: AsyncSession,
        *,
        actor: LocalActor,
        class_id: UUID,
        curriculum_subject_id: UUID,
    ) -> None:
        """Require access to one exact Class + CurriculumSubject scope."""

        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")

        classroom = await AcademicRepository.get_class_by_id(
            db,
            class_id,
        )

        if classroom is None:
            raise AcademicScopeError("Class does not exist or is no longer available")

        if not classroom.is_active:
            raise AcademicScopeError("Class is inactive")

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

        if actor.role == "admin":
            return

        if actor.role != "teacher":
            raise AcademicAuthorizationError(
                "Only administrators and teachers can access this academic scope"
            )

        teacher_membership_id = AcademicAuthorizationService._teacher_membership_id(
            actor
        )

        await AcademicAuthorizationService._require_live_teacher(
            db,
            teacher_membership_id=teacher_membership_id,
        )

        assignment = await AcademicRepository.get_active_assignment_for_scope(
            db,
            teacher_membership_id=teacher_membership_id,
            class_id=class_id,
            curriculum_subject_id=curriculum_subject_id,
        )

        if assignment is None:
            raise AcademicAuthorizationError(
                "Teacher does not have an active assignment "
                "for this class and curriculum subject"
            )

    @staticmethod
    async def list_actor_authorable_curriculum_subjects(
        db: AsyncSession,
        *,
        actor: LocalActor,
    ) -> list[CurriculumSubject]:
        """Return distinct CurriculumSubjects the actor may author content for."""

        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")

        if actor.role == "admin":
            return await AcademicRepository.list_all_active_curriculum_subjects(db)

        if actor.role != "teacher":
            raise AcademicAuthorizationError(
                "Only administrators and teachers can author academic content"
            )

        teacher_membership_id = AcademicAuthorizationService._teacher_membership_id(
            actor
        )

        await AcademicAuthorizationService._require_live_teacher(
            db,
            teacher_membership_id=teacher_membership_id,
        )

        candidates = (
            await AcademicRepository.list_authorable_curriculum_subjects_for_teacher(
                db,
                teacher_membership_id=teacher_membership_id,
            )
        )
        authorable: list[CurriculumSubject] = []
        for subject in candidates:
            assigned_classes = (
                await AcademicRepository.list_teacher_classes_for_curriculum_subject(
                    db,
                    teacher_membership_id=teacher_membership_id,
                    curriculum_subject_id=subject.id,
                )
            )
            if assigned_classes:
                authorable.append(subject)
        return authorable

    @staticmethod
    def _teacher_membership_id(actor: LocalActor) -> UUID:
        if actor.weave_membership_id is None:
            raise AcademicAuthorizationError(
                "Teacher is missing a Weave membership identity"
            )

        try:
            return UUID(actor.weave_membership_id)
        except ValueError as exc:
            raise AcademicAuthorizationError(
                "Teacher has an invalid Weave membership identity"
            ) from exc

    @staticmethod
    async def _require_live_teacher(
        db: AsyncSession,
        *,
        teacher_membership_id: UUID,
    ) -> None:
        teacher = await AcademicRepository.get_teacher_by_membership_id(
            db,
            teacher_membership_id,
        )

        if teacher is None:
            raise AcademicAuthorizationError(
                "Teacher is not available in the local academic projection"
            )

        if teacher.status != "active":
            raise AcademicAuthorizationError("Teacher is not currently active")

    @classmethod
    async def list_actor_effective_teacher_assignments(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
    ) -> list[TeacherAssignment]:
        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")

        if actor.role == "admin":
            return await AcademicRepository.list_effective_teacher_assignments(db)

        if actor.role != "teacher":
            raise AcademicAuthorizationError(
                "Only administrators and teachers can access teacher assignments"
            )

        teacher_membership_id = cls._teacher_membership_id(actor)

        await cls._require_live_teacher(
            db,
            teacher_membership_id=teacher_membership_id,
        )

        return await AcademicRepository.list_effective_teacher_assignments(
            db,
            teacher_membership_id=teacher_membership_id,
        )
