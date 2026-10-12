"""Application services for examination authoring and joint draft collaboration."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicScopeError
from app.domains.academics.authorization import AcademicAuthorizationService
from app.domains.academics.repository import AcademicRepository
from app.domains.auth.models import LocalActor
from app.domains.exams.exceptions import (
    ExamAuthorizationError,
    ExamNotFound,
    ExamStateError,
)
from app.domains.exams.models import (
    Exam,
    ExamQuestionSelection,
    ExamQuestionSelectionMode,
    ExamRosterStatus,
    ExamStatus,
)
from app.domains.exams.repository import ExamRepository
from app.domains.exams.schedule_validation import validate_normal_entry_window
from app.domains.exams.schemas import (
    ExamCreate,
    ExamQuestionConfiguration,
    ExamUpdate,
    ManualQuestionAdd,
    ManualQuestionRemove,
    ManualQuestionReorder,
)
from app.domains.questions.repository import QuestionRepository


def _normalize_optional_text(value: str | None) -> None | str:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ExamService:
    """Business operations for locally owned CBT examinations."""

    @staticmethod
    async def _before_create_exam_save(
        db: AsyncSession,
        *,
        payload: ExamCreate,
    ) -> None:
        return None

    @staticmethod
    async def _before_update_exam_save(
        db: AsyncSession,
        *,
        exam: Exam,
        session_id: UUID,
        term_id: UUID,
        scheduled_start_at: datetime | None,
        duration_minutes: int,
    ) -> None:
        return None

    @staticmethod
    async def _validate_random_question_capacity(
        db: AsyncSession,
        *,
        question_bank_id: UUID,
        question_count: int,
    ) -> None:
        active_question_count = await QuestionRepository.count_questions_for_bank(
            db,
            question_bank_id,
            active_only=True,
        )
        if active_question_count < question_count:
            raise ValueError(
                "Question bank does not contain enough active questions "
                "for the requested question count"
            )

    @staticmethod
    def _require_expected_authoring_version(
        exam: Exam,
        expected_authoring_version: int,
    ) -> None:
        if exam.authoring_version != expected_authoring_version:
            raise ExamStateError(
                "Examination changed since this screen was loaded. "
                "Refresh the paper before saving another change"
            )

    @staticmethod
    def _require_lead_or_admin(actor: LocalActor, exam: Exam) -> None:
        if not actor.is_active:
            raise ExamAuthorizationError("Active local actor is required")
        if actor.role == "admin":
            return
        if actor.role != "teacher" or actor.id != exam.created_by_actor_id:
            raise ExamAuthorizationError(
                "Only the lead author or a school administrator can perform "
                "this shared-paper operation"
            )

    @staticmethod
    def _bump_authoring_version(exam: Exam) -> None:
        exam.authoring_version += 1

    @classmethod
    async def create_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        payload: ExamCreate,
    ) -> Exam:
        session = await AcademicRepository.get_session_by_id(
            db,
            session_id=payload.session_id,
        )
        if session is None:
            raise AcademicScopeError(
                "Academic session does not exist or is no longer available"
            )

        term = await AcademicRepository.get_term_by_id(db, term_id=payload.term_id)
        if term is None:
            raise AcademicScopeError(
                "Academic term does not exist or is no longer available"
            )
        if term.academic_session_id != session.id:
            raise AcademicScopeError(
                "Academic term does not belong to the selected academic session"
            )

        # Any teacher who teaches this level-subject in at least one class that
        # is eligible for this term may start the one shared paper. The creator
        # becomes the coordinating lead for this revision.
        await (
            AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=payload.curriculum_subject_id,
                academic_term_id=term.id,
            )
        )

        assessment_scheme = await AcademicRepository.get_assessment_scheme_by_id(
            db,
            scheme_id=payload.assessment_scheme_id,
        )
        if assessment_scheme is None:
            raise AcademicScopeError(
                "Assessment scheme does not exist or is no longer available"
            )

        assessment_component = await AcademicRepository.get_component_by_id(
            db,
            component_id=payload.assessment_component_id,
        )
        if assessment_component is None:
            raise AcademicScopeError(
                "Assessment component does not exist or is no longer available"
            )
        if assessment_component.assessment_scheme_id != assessment_scheme.id:
            raise AcademicScopeError(
                "Assessment component does not belong to the selected assessment scheme"
            )

        question_bank = await QuestionRepository.get_bank_by_id(
            db,
            bank_id=payload.question_bank_id,
        )
        if question_bank is None:
            raise ValueError("Question bank does not exist")
        if not question_bank.is_active:
            raise ValueError("Question bank is inactive")
        if question_bank.curriculum_subject_id != payload.curriculum_subject_id:
            raise ValueError(
                "Question bank does not belong to the selected curriculum subject"
            )

        question_selection_mode = ExamQuestionSelectionMode(
            payload.question_selection_mode
        )
        if question_selection_mode == ExamQuestionSelectionMode.RANDOM:
            await cls._validate_random_question_capacity(
                db,
                question_bank_id=question_bank.id,
                question_count=payload.question_count,
            )

        # Title is presentation only. One revision-1 paper exists for the term,
        # level-subject and assessment component regardless of its title.
        existing_exam = await ExamRepository.get_exam_revision(
            db,
            term_id=payload.term_id,
            curriculum_subject_id=payload.curriculum_subject_id,
            assessment_component_id=payload.assessment_component_id,
            title=payload.title,
            revision_number=1,
        )
        if existing_exam is not None:
            raise ValueError(
                "An examination already exists for the selected term, "
                "curriculum subject and assessment component"
            )

        await cls._before_create_exam_save(db, payload=payload)

        exam = Exam(
            session_id=session.id,
            term_id=term.id,
            curriculum_subject_id=payload.curriculum_subject_id,
            assessment_scheme_id=assessment_scheme.id,
            assessment_component_id=assessment_component.id,
            question_bank_id=question_bank.id,
            question_selection_mode=question_selection_mode,
            question_count=payload.question_count,
            title=payload.title,
            instructions=_normalize_optional_text(payload.instructions),
            folder_color=payload.folder_color,
            duration_minutes=payload.duration_minutes,
            shuffle_questions=payload.shuffle_questions,
            shuffle_options=payload.shuffle_options,
            scheduled_start_at=payload.scheduled_start_at,
            latest_normal_start_at=payload.latest_normal_start_at,
            status=ExamStatus.DRAFT,
            roster_status=ExamRosterStatus.NOT_PREPARED,
            roster_version=0,
            roster_candidate_count=0,
            authoring_version=1,
            revision_number=1,
            revision_of_exam_id=None,
            created_by_actor_id=actor.id,
            component_maximum_score=None,
        )

        try:
            exam = await ExamRepository.add_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be created because its "
                "configuration conflicts with an existing shared paper"
            ) from exc
        return exam

    @classmethod
    async def update_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        payload: ExamUpdate,
        exam_id: UUID,
    ) -> Exam:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.DRAFT:
            raise ExamStateError("Only examinations in DRAFT state can be edited")

        cls._require_expected_authoring_version(
            exam,
            payload.expected_authoring_version,
        )
        cls._require_lead_or_admin(actor, exam)

        fields = payload.model_fields_set - {"expected_authoring_version"}
        if not fields:
            await db.commit()
            return exam

        required_fields = {
            "session_id",
            "term_id",
            "assessment_scheme_id",
            "assessment_component_id",
            "title",
            "duration_minutes",
            "shuffle_questions",
            "shuffle_options",
        }
        for field_name in required_fields:
            if field_name in fields and getattr(payload, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")

        next_session_id = (
            payload.session_id if "session_id" in fields else exam.session_id
        )
        next_term_id = payload.term_id if "term_id" in fields else exam.term_id
        next_assessment_scheme_id = (
            payload.assessment_scheme_id
            if "assessment_scheme_id" in fields
            else exam.assessment_scheme_id
        )
        next_assessment_component_id = (
            payload.assessment_component_id
            if "assessment_component_id" in fields
            else exam.assessment_component_id
        )
        next_title = payload.title if "title" in fields else exam.title
        next_duration_minutes = (
            payload.duration_minutes
            if "duration_minutes" in fields
            else exam.duration_minutes
        )
        next_shuffle_questions = (
            payload.shuffle_questions
            if "shuffle_questions" in fields
            else exam.shuffle_questions
        )
        next_shuffle_options = (
            payload.shuffle_options
            if "shuffle_options" in fields
            else exam.shuffle_options
        )

        assert next_session_id is not None
        assert next_term_id is not None
        assert next_assessment_scheme_id is not None
        assert next_assessment_component_id is not None
        assert next_title is not None
        assert next_duration_minutes is not None
        assert next_shuffle_questions is not None
        assert next_shuffle_options is not None

        session = await AcademicRepository.get_session_by_id(
            db,
            session_id=next_session_id,
        )
        if session is None:
            raise AcademicScopeError(
                "Academic session does not exist or is no longer available"
            )

        term = await AcademicRepository.get_term_by_id(db, term_id=next_term_id)
        if term is None:
            raise AcademicScopeError(
                "Academic term does not exist or is no longer available"
            )
        if term.academic_session_id != session.id:
            raise AcademicScopeError(
                "Academic term does not belong to the selected academic session"
            )

        # The lead must still be a legitimate author in the final term. Admins
        # remain the recovery path if teacher assignments change.
        await (
            AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
                academic_term_id=term.id,
            )
        )

        assessment_scheme = await AcademicRepository.get_assessment_scheme_by_id(
            db,
            scheme_id=next_assessment_scheme_id,
        )
        if assessment_scheme is None:
            raise AcademicScopeError(
                "Assessment scheme does not exist or is no longer available"
            )

        assessment_component = await AcademicRepository.get_component_by_id(
            db,
            component_id=next_assessment_component_id,
        )
        if assessment_component is None:
            raise AcademicScopeError(
                "Assessment component does not exist or is no longer available"
            )
        if assessment_component.assessment_scheme_id != assessment_scheme.id:
            raise AcademicScopeError(
                "Assessment component does not belong to the selected assessment scheme"
            )

        question_bank = await QuestionRepository.get_bank_by_id(
            db,
            bank_id=exam.question_bank_id,
        )
        if question_bank is None:
            raise ValueError("The examination question bank no longer exists")
        if not question_bank.is_active:
            raise ValueError("The examination question bank is inactive")
        if question_bank.curriculum_subject_id != exam.curriculum_subject_id:
            raise ValueError(
                "The examination question bank does not belong to "
                "the examination curriculum subject"
            )

        next_scheduled_start_at = (
            payload.scheduled_start_at
            if "scheduled_start_at" in fields
            else exam.scheduled_start_at
        )
        next_latest_normal_start_at = (
            payload.latest_normal_start_at
            if "latest_normal_start_at" in fields
            else exam.latest_normal_start_at
        )
        validate_normal_entry_window(
            next_scheduled_start_at, next_latest_normal_start_at
        )

        existing_exam = await ExamRepository.get_exam_revision(
            db,
            term_id=next_term_id,
            curriculum_subject_id=exam.curriculum_subject_id,
            assessment_component_id=next_assessment_component_id,
            title=next_title,
            revision_number=exam.revision_number,
        )
        if existing_exam is not None and existing_exam.id != exam.id:
            raise ValueError(
                "An examination already exists for the selected term, "
                "curriculum subject and assessment component"
            )

        await cls._before_update_exam_save(
            db,
            exam=exam,
            session_id=next_session_id,
            term_id=next_term_id,
            scheduled_start_at=next_scheduled_start_at,
            duration_minutes=next_duration_minutes,
        )

        if "session_id" in fields:
            exam.session_id = session.id
        if "term_id" in fields:
            exam.term_id = term.id
        if "assessment_scheme_id" in fields:
            exam.assessment_scheme_id = assessment_scheme.id
        if "assessment_component_id" in fields:
            exam.assessment_component_id = assessment_component.id
        if "title" in fields:
            exam.title = next_title
        if "instructions" in fields:
            exam.instructions = _normalize_optional_text(payload.instructions)
        if "folder_color" in fields:
            exam.folder_color = payload.folder_color
        if "duration_minutes" in fields:
            exam.duration_minutes = next_duration_minutes
        if "shuffle_questions" in fields:
            exam.shuffle_questions = next_shuffle_questions
        if "shuffle_options" in fields:
            exam.shuffle_options = next_shuffle_options
        if "scheduled_start_at" in fields:
            exam.scheduled_start_at = payload.scheduled_start_at
        if "latest_normal_start_at" in fields:
            exam.latest_normal_start_at = payload.latest_normal_start_at

        cls._bump_authoring_version(exam)
        try:
            exam = await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be updated because its "
                "configuration conflicts with existing examination data"
            ) from exc
        return exam

    @classmethod
    async def configure_questions(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        payload: ExamQuestionConfiguration,
    ) -> Exam:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.DRAFT:
            raise ExamStateError(
                "Questions can only be configured while the examination "
                "is in DRAFT state"
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

        question_selection_mode = ExamQuestionSelectionMode(
            payload.question_selection_mode
        )
        existing_selections = await ExamRepository.list_question_selections(
            db,
            exam.id,
        )
        bank_changed = question_bank.id != exam.question_bank_id
        preserve_manual_selections = (
            exam.question_selection_mode == ExamQuestionSelectionMode.MANUAL
            and question_selection_mode == ExamQuestionSelectionMode.MANUAL
            and not bank_changed
        )
        destructive_manual_change = (
            bool(existing_selections)
            and exam.question_selection_mode == ExamQuestionSelectionMode.MANUAL
            and (
                question_selection_mode != ExamQuestionSelectionMode.MANUAL
                or bank_changed
            )
        )
        if destructive_manual_change and not payload.clear_existing_manual_selections:
            raise ValueError(
                "This question configuration change would remove existing "
                "manual question selections. Set "
                "clear_existing_manual_selections=true to confirm the change"
            )

        should_clear_manual_selections = False
        if question_selection_mode == ExamQuestionSelectionMode.RANDOM:
            await cls._validate_random_question_capacity(
                db,
                question_bank_id=question_bank.id,
                question_count=payload.question_count,
            )
            should_clear_manual_selections = bool(existing_selections)
        elif question_selection_mode == ExamQuestionSelectionMode.MANUAL:
            if preserve_manual_selections:
                if len(existing_selections) > payload.question_count:
                    raise ValueError(
                        "Question count cannot be lower than the number "
                        "of manually selected questions"
                    )
            elif existing_selections:
                should_clear_manual_selections = True
        else:
            raise ValueError("Unsupported question selection mode")

        try:
            if should_clear_manual_selections:
                await ExamRepository.clear_question_selections(db, exam.id)

            exam.question_bank_id = question_bank.id
            exam.question_selection_mode = question_selection_mode
            exam.question_count = payload.question_count
            cls._bump_authoring_version(exam)
            exam = await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination question configuration could not be "
                "saved because it conflicts with existing examination data"
            ) from exc
        return exam

    @classmethod
    async def _require_manual_draft_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        expected_authoring_version: int,
    ) -> Exam:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.DRAFT:
            raise ExamStateError(
                "Manual questions can only be changed while the "
                "examination is in DRAFT state"
            )
        if exam.question_selection_mode != ExamQuestionSelectionMode.MANUAL:
            raise ExamStateError(
                "Manual questions can only be managed when the "
                "examination question selection mode is MANUAL"
            )

        cls._require_expected_authoring_version(exam, expected_authoring_version)
        await (
            AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
                academic_term_id=exam.term_id,
            )
        )
        return exam

    @classmethod
    async def list_manual_question_selections(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> list[ExamQuestionSelection]:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        await (
            AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
                academic_term_id=exam.term_id,
            )
        )
        return await ExamRepository.list_question_selections(db, exam.id)

    @classmethod
    async def add_manual_questions(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        payload: ManualQuestionAdd,
    ) -> Exam:
        exam = await cls._require_manual_draft_exam(
            db,
            actor=actor,
            exam_id=exam_id,
            expected_authoring_version=payload.expected_authoring_version,
        )
        question_ids = payload.question_ids
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Question selections cannot contain duplicate questions")

        question_bank = await QuestionRepository.get_bank_by_id(
            db,
            bank_id=exam.question_bank_id,
            lock=True,
        )
        if question_bank is None:
            raise ValueError("The examination question bank no longer exists")
        if not question_bank.is_active:
            raise ValueError("The examination question bank is inactive")
        if question_bank.curriculum_subject_id != exam.curriculum_subject_id:
            raise ValueError(
                "The examination question bank does not belong to "
                "the examination curriculum subject"
            )

        existing_selections = await ExamRepository.list_question_selections(db, exam.id)
        existing_question_ids = {row.question_id for row in existing_selections}
        if existing_question_ids & set(question_ids):
            raise ValueError(
                "One or more selected questions have already been "
                "added to this examination"
            )
        if len(existing_selections) + len(question_ids) > exam.question_count:
            raise ValueError(
                "Adding these questions would exceed the examination question count"
            )

        questions = await QuestionRepository.list_questions_by_ids(
            db,
            question_ids,
            active_only=True,
        )
        questions_by_id = {question.id: question for question in questions}
        if len(questions_by_id) != len(question_ids):
            raise ValueError(
                "One or more selected questions do not exist or are inactive"
            )
        for question_id in question_ids:
            if questions_by_id[question_id].bank_id != question_bank.id:
                raise ValueError(
                    "All selected questions must belong to the "
                    "examination question bank"
                )

        current_final_position = max(
            (row.position for row in existing_selections),
            default=0,
        )
        selections = [
            ExamQuestionSelection(
                exam_id=exam.id,
                question_id=question_id,
                added_by_actor_id=actor.id,
                position=current_final_position + offset,
            )
            for offset, question_id in enumerate(question_ids, start=1)
        ]

        try:
            await ExamRepository.add_question_selections(db, selections)
            cls._bump_authoring_version(exam)
            await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The selected questions could not be added because "
                "they conflict with the current examination selection"
            ) from exc
        return exam

    @classmethod
    async def remove_manual_question(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        payload: ManualQuestionRemove,
    ) -> Exam:
        exam = await cls._require_manual_draft_exam(
            db,
            actor=actor,
            exam_id=exam_id,
            expected_authoring_version=payload.expected_authoring_version,
        )
        selection = await ExamRepository.get_question_selection(
            db,
            exam_id=exam.id,
            question_id=payload.question_id,
            lock=True,
        )
        if selection is None:
            raise ValueError("Question is not selected for this examination")

        if (
            actor.role != "admin"
            and actor.id != exam.created_by_actor_id
            and actor.id != selection.added_by_actor_id
        ):
            raise ExamAuthorizationError(
                "A contributor may remove only questions they added; "
                "the lead author or administrator may manage the full paper"
            )

        current_selections = await ExamRepository.list_question_selections(db, exam.id)
        remaining = [
            row for row in current_selections if row.question_id != payload.question_id
        ]

        try:
            await ExamRepository.clear_question_selections(db, exam.id)
            if remaining:
                await ExamRepository.add_question_selections(
                    db,
                    [
                        ExamQuestionSelection(
                            exam_id=exam.id,
                            question_id=row.question_id,
                            added_by_actor_id=row.added_by_actor_id,
                            position=position,
                        )
                        for position, row in enumerate(remaining, start=1)
                    ],
                )
            cls._bump_authoring_version(exam)
            await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The manual question selection could not be updated "
                "because it conflicts with existing examination data"
            ) from exc
        return exam

    @classmethod
    async def reorder_manual_questions(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        payload: ManualQuestionReorder,
    ) -> Exam:
        exam = await cls._require_manual_draft_exam(
            db,
            actor=actor,
            exam_id=exam_id,
            expected_authoring_version=payload.expected_authoring_version,
        )
        cls._require_lead_or_admin(actor, exam)

        question_ids = payload.question_ids
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Question order cannot contain duplicate questions")

        current_selections = await ExamRepository.list_question_selections(db, exam.id)
        current_ids = [row.question_id for row in current_selections]
        if len(question_ids) != len(current_ids) or set(question_ids) != set(
            current_ids
        ):
            raise ValueError(
                "Question order must contain exactly the questions "
                "currently selected for this examination"
            )
        if question_ids == current_ids:
            await db.commit()
            return exam

        contributor_by_question = {
            row.question_id: row.added_by_actor_id for row in current_selections
        }
        try:
            await ExamRepository.clear_question_selections(db, exam.id)
            await ExamRepository.add_question_selections(
                db,
                [
                    ExamQuestionSelection(
                        exam_id=exam.id,
                        question_id=question_id,
                        added_by_actor_id=contributor_by_question[question_id],
                        position=position,
                    )
                    for position, question_id in enumerate(question_ids, start=1)
                ],
            )
            cls._bump_authoring_version(exam)
            await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The manual question order could not be updated because "
                "it conflicts with existing examination data"
            ) from exc
        return exam
