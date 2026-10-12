"""Examination submission, sealing, invigilation, and execution lifecycle services."""

from __future__ import annotations

from datetime import UTC, datetime
from secrets import SystemRandom
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.academics.authorization import AcademicAuthorizationService
from app.domains.academics.eligibility import AcademicEligibilityService
from app.domains.academics.repository import AcademicRepository
from app.domains.auth.models import LocalActor
from app.domains.exams.authoring_service import _normalize_optional_text
from app.domains.exams.exceptions import ExamNotFound, ExamStateError
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.models import (
    Exam,
    ExamInvigilator,
    ExamQuestion,
    ExamQuestionOption,
    ExamQuestionSelection,
    ExamQuestionSelectionMode,
    ExamRosterStatus,
    ExamStatus,
    ExamSuspension,
    ExamSuspensionSource,
    ExamTargetClass,
)
from app.domains.exams.repository import ExamRepository
from app.domains.questions.models import QuestionType
from app.domains.questions.repository import QuestionRepository
from app.domains.runtime.models import RealtimeOutboxEvent
from app.domains.runtime.repository import RuntimeRepository
from app.domains.sync.repository import SyncRepository


class _RandomQuestionCapacityValidator(Protocol):
    @staticmethod
    async def _validate_random_question_capacity(
        db: AsyncSession,
        *,
        question_bank_id: UUID,
        question_count: int,
    ) -> None: ...


class ExamLifecycleServiceMixin:
    """Lifecycle operations mixed into the public ExamService facade."""

    @staticmethod
    async def _before_activate_exam_save(
        db: AsyncSession,
        *,
        exam: Exam,
    ) -> None:
        return None

    @staticmethod
    async def _before_resume_exam_save(
        db: AsyncSession,
        *,
        exam: Exam,
    ) -> None:
        return None

    @staticmethod
    def _require_admin(actor: LocalActor) -> None:
        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")
        if actor.role != "admin":
            raise AcademicAuthorizationError(
                "Only school administrators can perform this exam operation"
            )

    @staticmethod
    def _normalize_required_text(
        value: str | None,
        field_name: str = "reason",
    ) -> str:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            raise ValueError(f"{field_name} is required")
        return normalized

    @staticmethod
    async def _add_lifecycle_event(
        db: AsyncSession,
        *,
        exam: Exam,
        event_type: str,
        actor: LocalActor,
        occurred_at: datetime,
        extra_payload: dict | None = None,
    ) -> None:
        """Persist one consistent transactional-outbox envelope."""

        payload = {
            "exam_id": str(exam.id),
            "status": exam.status.value,
            "revision_number": exam.revision_number,
            "actor_id": str(actor.id),
            "occurred_at": occurred_at.isoformat(),
        }
        if extra_payload:
            payload.update(extra_payload)

        await RuntimeRepository.add_outbox_event(
            db,
            RealtimeOutboxEvent(
                aggregate_type="exam",
                aggregate_id=exam.id,
                event_type=event_type,
                payload=payload,
            ),
        )

    @classmethod
    async def _latest_revision_in_lineage(
        cls,
        db: AsyncSession,
        exam: Exam,
    ) -> Exam:
        """Follow the unique revision chain to its current leaf under row locks."""

        current = exam
        while True:
            child = await ExamRepository.get_latest_child_revision(
                db,
                current.id,
                lock=True,
            )
            if child is None:
                return current
            current = child

    @classmethod
    async def _require_latest_revision(
        cls,
        db: AsyncSession,
        exam: Exam,
    ) -> Exam:
        latest = await cls._latest_revision_in_lineage(db, exam)
        if latest.id != exam.id:
            raise ExamStateError(
                "Only the latest examination revision can perform this operation"
            )
        return latest

    @classmethod
    async def submit_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        """Transition a complete DRAFT paper to SUBMITTED for admin review."""

        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.DRAFT:
            raise ExamStateError("Only examinations in DRAFT state can be submitted")

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=exam.curriculum_subject_id,
        )

        session = await AcademicRepository.get_session_by_id(
            db,
            session_id=exam.session_id,
        )
        if session is None:
            raise AcademicScopeError(
                "Academic session does not exist or is no longer available"
            )

        term = await AcademicRepository.get_term_by_id(db, term_id=exam.term_id)
        if term is None:
            raise AcademicScopeError(
                "Academic term does not exist or is no longer available"
            )
        if term.academic_session_id != session.id:
            raise AcademicScopeError(
                "Academic term does not belong to the examination academic session"
            )

        assessment_scheme = await AcademicRepository.get_assessment_scheme_by_id(
            db,
            scheme_id=exam.assessment_scheme_id,
        )
        if assessment_scheme is None:
            raise AcademicScopeError(
                "Assessment scheme does not exist or is no longer available"
            )

        assessment_component = await AcademicRepository.get_component_by_id(
            db,
            component_id=exam.assessment_component_id,
        )
        if assessment_component is None:
            raise AcademicScopeError(
                "Assessment component does not exist or is no longer available"
            )
        if assessment_component.assessment_scheme_id != assessment_scheme.id:
            raise AcademicScopeError(
                "Assessment component does not belong to the examination assessment scheme"
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

        if (
            exam.scheduled_start_at is not None
            and exam.latest_normal_start_at is not None
            and exam.latest_normal_start_at < exam.scheduled_start_at
        ):
            raise ValueError(
                "latest_normal_start_at cannot be earlier than scheduled_start_at"
            )

        selection_mode = ExamQuestionSelectionMode(exam.question_selection_mode)

        if selection_mode == ExamQuestionSelectionMode.RANDOM:
            await cast(
                _RandomQuestionCapacityValidator,
                cls,
            )._validate_random_question_capacity(
                db,
                question_bank_id=question_bank.id,
                question_count=exam.question_count,
            )
            existing_selections = await ExamRepository.list_question_selections(
                db,
                exam.id,
            )
            if existing_selections:
                raise ValueError(
                    "RANDOM examinations cannot contain manual question selections"
                )

        elif selection_mode == ExamQuestionSelectionMode.MANUAL:
            selections = await ExamRepository.list_question_selections(db, exam.id)
            if len(selections) != exam.question_count:
                raise ValueError(
                    "A MANUAL examination must contain exactly "
                    f"{exam.question_count} selected questions before submission"
                )

            expected_positions = list(range(1, exam.question_count + 1))
            actual_positions = [selection.position for selection in selections]
            if actual_positions != expected_positions:
                raise ValueError(
                    "Manual question selections must have continuous positions "
                    "before submission"
                )

            selected_question_ids = [selection.question_id for selection in selections]
            questions = await QuestionRepository.list_questions_by_ids(
                db,
                selected_question_ids,
                active_only=True,
            )
            questions_by_id = {question.id: question for question in questions}
            if len(questions_by_id) != len(selected_question_ids):
                raise ValueError(
                    "One or more manually selected questions no longer exist or are inactive"
                )

            for question_id in selected_question_ids:
                if questions_by_id[question_id].bank_id != question_bank.id:
                    raise ValueError(
                        "All manually selected questions must belong to "
                        "the examination question bank"
                    )
        else:
            raise ValueError("Unsupported question selection mode")

        exam.status = ExamStatus.SUBMITTED
        exam.submitted_by_actor_id = actor.id
        exam.submitted_at = datetime.now(UTC)

        try:
            exam = await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be submitted because its "
                "current state conflicts with existing examination data"
            ) from exc

        return exam

    @classmethod
    async def _resolve_questions_for_sealing(
        cls,
        db: AsyncSession,
        *,
        exam: Exam,
    ) -> list:
        """Resolve and lock the exact source questions for the immutable paper."""

        if exam.question_selection_mode == ExamQuestionSelectionMode.RANDOM:
            available_questions = await QuestionRepository.list_questions_for_bank(
                db,
                exam.question_bank_id,
                active_only=True,
            )
            if len(available_questions) < exam.question_count:
                raise ValueError(
                    "Question bank no longer contains enough active questions "
                    "to seal this examination"
                )

            selected_ids = SystemRandom().sample(
                [question.id for question in available_questions],
                exam.question_count,
            )
            selected_questions = await QuestionRepository.list_questions_by_ids(
                db,
                selected_ids,
                active_only=True,
                lock=True,
            )
            questions_by_id = {question.id: question for question in selected_questions}
            if len(questions_by_id) != exam.question_count:
                raise ValueError(
                    "One or more randomly selected questions became unavailable "
                    "while sealing the examination"
                )
            return [questions_by_id[question_id] for question_id in selected_ids]

        if exam.question_selection_mode == ExamQuestionSelectionMode.MANUAL:
            selections = await ExamRepository.list_question_selections(db, exam.id)
            if len(selections) != exam.question_count:
                raise ValueError(
                    "A MANUAL examination must contain exactly "
                    f"{exam.question_count} selected questions before sealing"
                )

            expected_positions = list(range(1, exam.question_count + 1))
            actual_positions = [selection.position for selection in selections]
            if actual_positions != expected_positions:
                raise ValueError(
                    "Manual question selections must have continuous positions "
                    "before sealing"
                )

            selected_ids = [selection.question_id for selection in selections]
            selected_questions = await QuestionRepository.list_questions_by_ids(
                db,
                selected_ids,
                active_only=True,
                lock=True,
            )
            questions_by_id = {question.id: question for question in selected_questions}
            if len(questions_by_id) != exam.question_count:
                raise ValueError(
                    "One or more manually selected questions no longer exist or are inactive"
                )
            return [questions_by_id[question_id] for question_id in selected_ids]

        raise ValueError("Unsupported question selection mode")

    @staticmethod
    async def _validate_questions_for_sealing(
        db: AsyncSession,
        *,
        exam: Exam,
        questions: list,
    ) -> dict[UUID, list]:
        """Validate executable choice-question invariants and return their options."""

        question_ids = [question.id for question in questions]
        options = await QuestionRepository.list_options_for_questions(
            db,
            question_ids,
        )
        options_by_question_id: dict[UUID, list] = {
            question_id: [] for question_id in question_ids
        }
        for option in options:
            options_by_question_id[option.question_id].append(option)

        for question in questions:
            if question.bank_id != exam.question_bank_id:
                raise ValueError(
                    "All examination questions must belong to the examination question bank"
                )

            question_options = options_by_question_id[question.id]
            if len(question_options) < 2:
                raise ValueError(
                    "Every examination question must contain at least two answer options"
                )

            expected_positions = list(range(1, len(question_options) + 1))
            actual_positions = [option.position for option in question_options]
            if actual_positions != expected_positions:
                raise ValueError(
                    "Question options must have continuous positions before "
                    "the examination can be sealed"
                )

            comparable_content: list[tuple[str | None, UUID | None]] = []
            for option in question_options:
                normalized_text = (
                    option.text.strip().casefold() if option.text else None
                )
                if normalized_text is None and option.image_asset_id is None:
                    raise ValueError(
                        "Every examination answer option must contain text, an image, or both"
                    )
                comparable_content.append((normalized_text, option.image_asset_id))
            if len(comparable_content) != len(set(comparable_content)):
                raise ValueError(
                    "Question options must be unique before the examination can be sealed"
                )

            correct_count = sum(1 for option in question_options if option.is_correct)
            if question.question_type == QuestionType.SINGLE_CHOICE:
                if correct_count != 1:
                    raise ValueError(
                        "A single-choice examination question must have exactly "
                        "one correct option"
                    )
            elif question.question_type == QuestionType.MULTIPLE_CHOICE:
                if correct_count < 2:
                    raise ValueError(
                        "A multiple-choice examination question must have at least "
                        "two correct options"
                    )
                if correct_count == len(question_options):
                    raise ValueError(
                        "A multiple-choice examination question must have at least "
                        "one incorrect option"
                    )
            else:
                raise ValueError("Unsupported examination question type")

        return options_by_question_id

    @classmethod
    async def seal_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        """Permanently freeze one submitted exam revision."""

        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.SUBMITTED:
            raise ExamStateError("Only examinations in SUBMITTED state can be sealed")

        cls._require_admin(actor)

        # Cloud -> CBT sync also acquires this transaction-scoped advisory lock.
        # Holding it while resolving academic scope guarantees that every synced
        # projection used to freeze ExamTargetClass comes from one coherent graph.
        await SyncRepository.acquire_apply_lock(db)

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=exam.curriculum_subject_id,
        )

        session = await AcademicRepository.get_session_by_id(
            db,
            session_id=exam.session_id,
        )
        if session is None:
            raise AcademicScopeError(
                "Academic session does not exist or is no longer available"
            )

        term = await AcademicRepository.get_term_by_id(db, term_id=exam.term_id)
        if term is None:
            raise AcademicScopeError(
                "Academic term does not exist or is no longer available"
            )
        if term.academic_session_id != session.id:
            raise AcademicScopeError(
                "Academic term does not belong to the examination academic session"
            )

        assessment_scheme = await AcademicRepository.get_assessment_scheme_by_id(
            db,
            scheme_id=exam.assessment_scheme_id,
        )
        if assessment_scheme is None:
            raise AcademicScopeError(
                "Assessment scheme does not exist or is no longer available"
            )
        if assessment_scheme.status != "active":
            raise AcademicScopeError("Assessment scheme is no longer active")

        assessment_component = await AcademicRepository.get_component_by_id(
            db,
            component_id=exam.assessment_component_id,
        )
        if assessment_component is None:
            raise AcademicScopeError(
                "Assessment component does not exist or is no longer available"
            )
        if not assessment_component.is_active:
            raise AcademicScopeError("Assessment component is no longer active")
        if assessment_component.assessment_scheme_id != assessment_scheme.id:
            raise AcademicScopeError(
                "Assessment component does not belong to the examination assessment scheme"
            )

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

        if await ExamRepository.count_exam_questions(db, exam.id):
            raise ExamStateError(
                "Submitted examination already contains frozen questions"
            )

        questions = await cls._resolve_questions_for_sealing(db, exam=exam)
        if len(questions) != exam.question_count:
            raise ValueError(
                "Resolved examination question count does not match "
                "the configured question count"
            )

        options_by_question_id = await cls._validate_questions_for_sealing(
            db,
            exam=exam,
            questions=questions,
        )

        # Preserve manual-paper contribution before the temporary
        # ExamQuestionSelection rows are deleted during sealing

        # Random papers have no explicit contributor because the system chooses
        # their questions automatically

        contributor_by_question_id: dict[UUID, UUID] = {}

        if exam.question_selection_mode == ExamQuestionSelectionMode.MANUAL:
            selections = await ExamRepository.list_question_selections(db, exam.id)

            contributor_by_question_id = {
                selection.question_id: selection.added_by_actor_id
                for selection in selections
            }

            missing_contributor_ids = [
                question.id
                for question in questions
                if question.id not in contributor_by_question_id
            ]

            if missing_contributor_ids:
                raise ExamStateError(
                    "Manual examination question contributor provenance is incomplete"
                )

        # The examination remains level-wide. At sealing, freeze the classes
        # that are academically eligible for this subject in this exact term.
        # Teacher assignments are authoring authority, not delivery scope.
        eligible_classes = await AcademicEligibilityService.list_eligible_classes(
            db,
            curriculum_subject_id=exam.curriculum_subject_id,
            academic_term_id=exam.term_id,
        )
        target_classes = [
            ExamTargetClass(
                exam_id=exam.id,
                class_id=classroom.id,
                teacher_assignment_id=None,
            )
            for classroom in eligible_classes
        ]

        if not target_classes:
            raise AcademicScopeError(
                "Examination has no academically eligible target classes "
                "for the selected term"
            )

        frozen_questions = [
            ExamQuestion(
                exam_id=exam.id,
                source_question_id=question.id,
                source_question_version=question.version,
                added_by_actor_id=contributor_by_question_id.get(question.id),
                question_type=question.question_type,
                position=position,
                prompt=question.prompt,
                instruction=question.instruction,
                image_asset_id=question.image_asset_id,
            )
            for position, question in enumerate(questions, start=1)
        ]
        sealed_at = datetime.now(UTC)

        try:
            frozen_questions = await ExamRepository.add_exam_questions(
                db,
                frozen_questions,
            )
            frozen_by_source_id = {
                frozen_question.source_question_id: frozen_question
                for frozen_question in frozen_questions
            }

            frozen_options: list[ExamQuestionOption] = []
            for source_question in questions:
                frozen_question = frozen_by_source_id[source_question.id]
                for source_option in options_by_question_id[source_question.id]:
                    frozen_options.append(
                        ExamQuestionOption(
                            exam_question_id=frozen_question.id,
                            position=source_option.position,
                            text=source_option.text,
                            image_asset_id=source_option.image_asset_id,
                            is_correct=source_option.is_correct,
                        )
                    )

            await ExamRepository.add_exam_question_options(db, frozen_options)
            await ExamRepository.add_target_classes(db, target_classes)

            if exam.question_selection_mode == ExamQuestionSelectionMode.MANUAL:
                await ExamRepository.clear_question_selections(db, exam.id)

            exam.component_maximum_score = assessment_component.maximum_score
            exam.status = ExamStatus.SEALED
            exam.sealed_by_actor_id = actor.id
            exam.sealed_at = sealed_at
            exam.roster_status = ExamRosterStatus.PENDING
            exam.roster_candidate_count = 0
            exam.roster_prepared_at = None
            exam.roster_error = None

            exam = await ExamRepository.save_exam(db, exam)
            await cls._add_lifecycle_event(
                db,
                exam=exam,
                event_type="exam.sealed",
                actor=actor,
                occurred_at=sealed_at,
                extra_payload={
                    "question_count": exam.question_count,
                    "target_class_count": len(target_classes),
                    "roster_status": ExamRosterStatus.PENDING.value,
                },
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be sealed because its final "
                "configuration conflicts with existing examination data"
            ) from exc

        return exam

    @classmethod
    async def return_exam_to_draft(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
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

    @classmethod
    async def delete_draft_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
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

        # created_by_actor_id is provenance, not ownership. Any teacher who is
        # currently authorized for the shared curriculum-subject draft may delete
        # it; administrators are also allowed.
        if actor.role == "admin":
            cls._require_admin(actor)
        else:
            await AcademicAuthorizationService.require_can_author_curriculum_subject(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
            )

        try:
            await ExamRepository.delete_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The draft examination could not be deleted because it is "
                "referenced by existing examination data"
            ) from exc

    @classmethod
    async def list_available_invigilators(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
    ) -> list:
        cls._require_admin(actor)
        return await AcademicRepository.list_teachers(db, active_only=True)

    @classmethod
    async def list_invigilators(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> list[ExamInvigilator]:
        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        return await ExamRepository.list_invigilators_for_exam(db, exam.id)

    @classmethod
    async def assign_invigilators(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        teacher_ids: list[UUID],
    ) -> list[ExamInvigilator]:
        cls._require_admin(actor)
        unique_teacher_ids = list(dict.fromkeys(teacher_ids))
        if not unique_teacher_ids:
            raise ValueError("At least one teacher must be selected")

        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status in {ExamStatus.CLOSED, ExamStatus.CANCELLED}:
            raise ExamStateError(
                "Invigilators cannot be changed after an examination is "
                "closed or cancelled"
            )

        teachers = await AcademicRepository.list_teachers_by_ids(
            db,
            unique_teacher_ids,
            active_only=True,
        )
        found_teacher_ids = {teacher.id for teacher in teachers}
        missing_ids = [
            teacher_id
            for teacher_id in unique_teacher_ids
            if teacher_id not in found_teacher_ids
        ]
        if missing_ids:
            raise AcademicScopeError(
                "One or more teachers do not exist, are inactive, or have been deleted"
            )

        existing = await ExamRepository.list_invigilators_for_exam_and_teachers(
            db,
            exam_id=exam.id,
            teacher_ids=unique_teacher_ids,
            lock=True,
        )
        existing_teacher_ids = {row.teacher_id for row in existing}
        new_rows = [
            ExamInvigilator(exam_id=exam.id, teacher_id=teacher_id)
            for teacher_id in unique_teacher_ids
            if teacher_id not in existing_teacher_ids
        ]

        try:
            created = await ExamRepository.add_invigilators(db, new_rows)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "Invigilators could not be assigned because the assignment "
                "conflicts with existing examination data"
            ) from exc

        return [*existing, *created]

    @classmethod
    async def remove_invigilators(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        teacher_ids: list[UUID],
    ) -> list[ExamInvigilator]:
        cls._require_admin(actor)
        unique_teacher_ids = list(dict.fromkeys(teacher_ids))
        if not unique_teacher_ids:
            raise ValueError("At least one teacher must be selected")

        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status in {ExamStatus.CLOSED, ExamStatus.CANCELLED}:
            raise ExamStateError(
                "Invigilators cannot be changed after an examination is "
                "closed or cancelled"
            )

        try:
            await ExamRepository.remove_invigilators_by_teacher_ids(
                db,
                exam_id=exam.id,
                teacher_ids=unique_teacher_ids,
            )
            remaining = await ExamRepository.list_invigilators_for_exam(db, exam.id)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "Invigilators could not be removed because the assignment "
                "conflicts with existing examination data"
            ) from exc

        return remaining

    @classmethod
    async def create_revision(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        latest = await cls._latest_revision_in_lineage(db, exam)
        if latest.status == ExamStatus.CLOSED:
            if not await ExamExecutionService.results_are_voided(db, exam_id=latest.id):
                raise ExamStateError(
                    "A CLOSED examination can only be revised when its results are voided"
                )
        elif latest.status not in {ExamStatus.SEALED, ExamStatus.CANCELLED}:
            raise ExamStateError(
                "A new revision can only be created from the latest SEALED "
                "or CANCELLED examination revision, or a CLOSED revision with VOIDED results"
            )

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=latest.curriculum_subject_id,
        )

        revision = Exam(
            session_id=latest.session_id,
            term_id=latest.term_id,
            curriculum_subject_id=latest.curriculum_subject_id,
            assessment_scheme_id=latest.assessment_scheme_id,
            assessment_component_id=latest.assessment_component_id,
            question_bank_id=latest.question_bank_id,
            question_selection_mode=latest.question_selection_mode,
            question_count=latest.question_count,
            title=latest.title,
            instructions=latest.instructions,
            duration_minutes=latest.duration_minutes,
            shuffle_questions=latest.shuffle_questions,
            shuffle_options=latest.shuffle_options,
            scheduled_start_at=latest.scheduled_start_at,
            latest_normal_start_at=latest.latest_normal_start_at,
            status=ExamStatus.DRAFT,
            roster_status=ExamRosterStatus.NOT_PREPARED,
            roster_version=0,
            roster_candidate_count=0,
            revision_number=latest.revision_number + 1,
            revision_of_exam_id=latest.id,
            created_by_actor_id=actor.id,
            component_maximum_score=None,
        )

        try:
            revision = await ExamRepository.add_exam(db, revision)
            if revision.question_selection_mode == ExamQuestionSelectionMode.MANUAL:
                frozen_questions = await ExamRepository.list_exam_questions(
                    db,
                    latest.id,
                )

                missing_contributor_ids = [
                    question.source_question_id
                    for question in frozen_questions
                    if question.added_by_actor_id is None
                ]

                if missing_contributor_ids:
                    raise ExamStateError(
                        "Manual examination revision cannot be created because "
                        "question contributor provenance is incomplete"
                    )

                await ExamRepository.add_question_selections(
                    db,
                    [
                        ExamQuestionSelection(
                            exam_id=revision.id,
                            added_by_actor_id=question.added_by_actor_id,
                            question_id=question.source_question_id,
                            position=question.position,
                        )
                        for question in frozen_questions
                    ],
                )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination revision could not be created because it "
                "conflicts with existing examination data"
            ) from exc

        return revision

    @classmethod
    async def activate_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.SEALED:
            raise ExamStateError("Only SEALED examinations can be activated")

        await cls._require_latest_revision(db, exam)

        if exam.roster_status != ExamRosterStatus.READY:
            raise ExamStateError("Candidate roster must be READY before activation")
        frozen_count = await ExamRepository.count_exam_questions(db, exam.id)
        if frozen_count != exam.question_count:
            raise ExamStateError("Frozen question count does not match exam setup")
        if exam.sealed_at is None or exam.component_maximum_score is None:
            raise ExamStateError("Exam is missing required sealed state")

        await cls._before_activate_exam_save(db, exam=exam)

        activated_at = datetime.now(UTC)
        exam.status = ExamStatus.ACTIVE
        exam.activated_by_actor_id = actor.id
        exam.activated_at = activated_at

        try:
            exam = await ExamRepository.save_exam(db, exam)
            await cls._add_lifecycle_event(
                db,
                exam=exam,
                event_type="exam.activated",
                actor=actor,
                occurred_at=activated_at,
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be activated because its "
                "current state conflicts with existing examination data"
            ) from exc

        return exam

    @classmethod
    async def suspend_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        reason: str,
    ) -> Exam:
        cls._require_admin(actor)
        reason = cls._normalize_required_text(reason)
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.ACTIVE:
            raise ExamStateError("Only ACTIVE examinations can be suspended")

        suspended_at = datetime.now(UTC)
        exam.status = ExamStatus.SUSPENDED
        suspension = ExamSuspension(
            exam_id=exam.id,
            source=ExamSuspensionSource.ADMIN,
            suspended_at=suspended_at,
            suspended_by_actor_id=actor.id,
            reason=reason,
        )

        try:
            await ExamRepository.add_suspension(db, suspension)
            exam = await ExamRepository.save_exam(db, exam)
            await cls._add_lifecycle_event(
                db,
                exam=exam,
                event_type="exam.suspended",
                actor=actor,
                occurred_at=suspended_at,
                extra_payload={"reason": reason},
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be suspended because its "
                "current state conflicts with existing examination data"
            ) from exc

        return exam

    @classmethod
    async def resume_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        reason: str | None = None,
    ) -> Exam:
        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.SUSPENDED:
            raise ExamStateError("Only SUSPENDED examinations can be resumed")

        suspension = await ExamRepository.get_open_suspension_for_exam(
            db,
            exam.id,
            lock=True,
        )
        if suspension is None:
            raise ExamStateError("Suspended examination has no open suspension")

        resumed_at = datetime.now(UTC)
        suspension.resumed_at = resumed_at
        suspension.resumed_by_actor_id = actor.id
        suspension.resume_reason = _normalize_optional_text(reason)

        await cls._before_resume_exam_save(db, exam=exam)

        exam.status = ExamStatus.ACTIVE

        try:
            await ExamRepository.save_suspension(db, suspension)
            exam = await ExamRepository.save_exam(db, exam)
            await cls._add_lifecycle_event(
                db,
                exam=exam,
                event_type="exam.resumed",
                actor=actor,
                occurred_at=resumed_at,
                extra_payload={"reason": suspension.resume_reason},
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be resumed because its "
                "current state conflicts with existing examination data"
            ) from exc

        return exam

    @classmethod
    async def close_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status not in {ExamStatus.ACTIVE, ExamStatus.SUSPENDED}:
            raise ExamStateError("Only ACTIVE or SUSPENDED examinations can be closed")

        closed_at = datetime.now(UTC)
        suspension = None
        if exam.status == ExamStatus.SUSPENDED:
            suspension = await ExamRepository.get_open_suspension_for_exam(
                db,
                exam.id,
                lock=True,
            )
            if suspension is None:
                raise ExamStateError("Suspended examination has no open suspension")
            suspension.resumed_at = closed_at
            suspension.resumed_by_actor_id = actor.id
            suspension.resume_reason = "Closed while suspended"

        exam.status = ExamStatus.CLOSED
        exam.closed_by_actor_id = actor.id
        exam.closed_at = closed_at

        try:
            if suspension is not None:
                await ExamRepository.save_suspension(db, suspension)
            exam = await ExamRepository.save_exam(db, exam)
            await cls._add_lifecycle_event(
                db,
                exam=exam,
                event_type="exam.closed",
                actor=actor,
                occurred_at=closed_at,
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be closed because its "
                "current state conflicts with existing examination data"
            ) from exc

        return exam

    @classmethod
    async def cancel_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        reason: str,
    ) -> Exam:
        cls._require_admin(actor)
        reason = cls._normalize_required_text(reason)
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status not in {
            ExamStatus.SEALED,
            ExamStatus.ACTIVE,
            ExamStatus.SUSPENDED,
        }:
            raise ExamStateError(
                "Only SEALED, ACTIVE, or SUSPENDED examinations can be cancelled"
            )

        cancelled_at = datetime.now(UTC)
        suspension = None
        if exam.status == ExamStatus.SUSPENDED:
            suspension = await ExamRepository.get_open_suspension_for_exam(
                db,
                exam.id,
                lock=True,
            )
            if suspension is None:
                raise ExamStateError("Suspended examination has no open suspension")
            suspension.resumed_at = cancelled_at
            suspension.resumed_by_actor_id = actor.id
            suspension.resume_reason = "Cancelled while suspended"

        exam.status = ExamStatus.CANCELLED
        exam.cancelled_by_actor_id = actor.id
        exam.cancelled_at = cancelled_at
        exam.cancellation_reason = reason

        try:
            if suspension is not None:
                await ExamRepository.save_suspension(db, suspension)
            exam = await ExamRepository.save_exam(db, exam)
            await cls._add_lifecycle_event(
                db,
                exam=exam,
                event_type="exam.cancelled",
                actor=actor,
                occurred_at=cancelled_at,
                extra_payload={"reason": reason},
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination could not be cancelled because its "
                "current state conflicts with existing examination data"
            ) from exc

        return exam
