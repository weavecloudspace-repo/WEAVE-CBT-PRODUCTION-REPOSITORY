"""Joint-authoring guards for examination lifecycle transitions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.authorization import AcademicAuthorizationService
from app.domains.auth.models import LocalActor
from app.domains.exams.exceptions import ExamNotFound, ExamStateError
from app.domains.exams.models import (
    Exam,
    ExamQuestionSelection,
    ExamQuestionSelectionMode,
    ExamStatus,
)
from app.domains.exams.question_authoring_schema import ExamQuestionAuthoringSave
from app.domains.exams.repository import ExamRepository
from app.domains.questions.repository import QuestionRepository


class ExamCollaborationLifecycleMixin:
    """Apply shared-paper coordination rules before lifecycle transitions."""

    @classmethod
    async def save_question_authoring(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        payload: ExamQuestionAuthoringSave,
    ) -> Exam:
        """Save question configuration plus the resulting manual paper atomically.

        This is the lead/admin authoring path. It deliberately accepts the final
        effective state so the UI can change question count, bank or selection
        mode and shape the manual selection before any prerequisite mutation is
        committed.
        """

        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.DRAFT:
            raise ExamStateError(
                "Question authoring can only be saved while the examination is in DRAFT state"
            )

        cls._require_expected_authoring_version(
            exam,
            payload.expected_authoring_version,
        )
        cls._require_lead_or_admin(actor, exam)
        await (
            AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
                academic_term_id=exam.term_id,
            )
        )

        question_bank = await QuestionRepository.get_bank_by_id(
            db,
            bank_id=payload.question_bank_id,
            lock=True,
        )
        if question_bank is None:
            raise ValueError("Question bank does not exist")
        if not question_bank.is_active:
            raise ValueError("Question bank is inactive")
        if question_bank.curriculum_subject_id != exam.curriculum_subject_id:
            raise ValueError(
                "Question bank does not belong to the examination curriculum subject"
            )

        mode = ExamQuestionSelectionMode(payload.question_selection_mode)
        question_ids = list(payload.manual_question_ids)
        existing_selections = await ExamRepository.list_question_selections(db, exam.id)
        current_ids = [row.question_id for row in existing_selections]
        existing_by_question = {row.question_id: row for row in existing_selections}

        if mode == ExamQuestionSelectionMode.RANDOM:
            if question_ids:
                raise ValueError(
                    "Random selection cannot include manual question selections"
                )
            await cls._validate_random_question_capacity(
                db,
                question_bank_id=question_bank.id,
                question_count=payload.question_count,
            )
        elif mode == ExamQuestionSelectionMode.MANUAL:
            if len(question_ids) > payload.question_count:
                raise ValueError(
                    "Manual selections cannot exceed the examination question count"
                )

            questions = await QuestionRepository.list_questions_by_ids(
                db,
                question_ids,
                active_only=False,
                lock=True,
            )
            questions_by_id = {question.id: question for question in questions}
            if len(questions_by_id) != len(question_ids):
                raise ValueError("One or more selected questions no longer exist")

            newly_selected_ids = set(question_ids) - set(existing_by_question)
            for question_id in question_ids:
                question = questions_by_id[question_id]
                if question.bank_id != question_bank.id:
                    raise ValueError(
                        "All selected questions must belong to the selected question bank"
                    )
                if question_id in newly_selected_ids and not question.is_active:
                    raise ValueError(
                        "Archived questions cannot be newly added to an examination"
                    )
        else:
            raise ValueError("Unsupported question selection mode")

        current_mode = ExamQuestionSelectionMode(exam.question_selection_mode)
        effective_ids = question_ids if mode == ExamQuestionSelectionMode.MANUAL else []
        changed = bool(
            exam.question_bank_id != question_bank.id
            or current_mode != mode
            or exam.question_count != payload.question_count
            or current_ids != effective_ids
        )
        if not changed:
            await db.commit()
            return exam

        try:
            if existing_selections:
                await ExamRepository.clear_question_selections(db, exam.id)

            if mode == ExamQuestionSelectionMode.MANUAL and question_ids:
                await ExamRepository.add_question_selections(
                    db,
                    [
                        ExamQuestionSelection(
                            exam_id=exam.id,
                            question_id=question_id,
                            added_by_actor_id=(
                                existing_by_question[question_id].added_by_actor_id
                                if question_id in existing_by_question
                                else actor.id
                            ),
                            position=position,
                        )
                        for position, question_id in enumerate(question_ids, start=1)
                    ],
                )

            exam.question_bank_id = question_bank.id
            exam.question_selection_mode = mode
            exam.question_count = payload.question_count
            cls._bump_authoring_version(exam)
            exam = await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination question setup could not be saved because it conflicts with the current paper"
            ) from exc

        return exam

    @classmethod
    async def submit_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        expected_authoring_version: int = 1,
    ) -> Exam:
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.DRAFT:
            raise ExamStateError("Only examinations in DRAFT state can be submitted")

        cls._require_expected_authoring_version(exam, expected_authoring_version)
        cls._require_lead_or_admin(actor, exam)
        await (
            AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
                academic_term_id=exam.term_id,
            )
        )

        # Stage the version bump in the same transaction used by the existing
        # submit implementation. If submission validation fails, roll back both.
        cls._bump_authoring_version(exam)
        await ExamRepository.save_exam(db, exam)
        try:
            return await super().submit_exam(
                db,
                actor=actor,
                exam_id=exam_id,
            )
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def delete_draft_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        expected_authoring_version: int = 1,
    ) -> None:
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.DRAFT:
            raise ExamStateError("Only DRAFT examinations can be deleted")

        cls._require_expected_authoring_version(exam, expected_authoring_version)
        cls._require_lead_or_admin(actor, exam)
        await (
            AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
                academic_term_id=exam.term_id,
            )
        )

        await super().delete_draft_exam(
            db,
            actor=actor,
            exam_id=exam_id,
        )

    @classmethod
    async def return_exam_to_draft(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        """Return a submitted paper to draft and invalidate old authoring screens."""

        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.SUBMITTED:
            raise ExamStateError(
                "Only examinations in SUBMITTED state can return to draft"
            )

        exam.status = ExamStatus.DRAFT
        exam.submitted_by_actor_id = None
        exam.submitted_at = None
        cls._bump_authoring_version(exam)

        try:
            exam = await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not return to draft because its "
                "current state conflicts with existing examination data"
            ) from exc
        return exam
