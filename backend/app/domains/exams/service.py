"""Public examination service facade."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.academics.authorization import AcademicAuthorizationService
from app.domains.academics.eligibility import AcademicEligibilityService
from app.domains.academics.repository import AcademicRepository
from app.domains.auth.models import LocalActor
from app.domains.exams.authoring_service import ExamService as _AuthoringExamService
from app.domains.exams.collaboration_service import ExamCollaborationLifecycleMixin
from app.domains.exams.exceptions import (
    ExamAuthorizationError,
    ExamNotFound,
    ExamStateError,
)
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.lifecycle_service import ExamLifecycleServiceMixin
from app.domains.exams.models import (
    Exam,
    ExamQuestionSelection,
    ExamQuestionSelectionMode,
    ExamRosterStatus,
    ExamStatus,
)
from app.domains.exams.repository import ExamRepository
from app.domains.exams.schedule_validation import validate_normal_entry_window
from app.domains.exams.schemas import ExamCreate, ExamUpdate, ManualQuestionRemove
from app.domains.exams.timetable_service import ExamTimetableService
from app.domains.questions.repository import QuestionRepository
from app.workers.producer import arq_producer


class ExamService(
    ExamCollaborationLifecycleMixin,
    ExamLifecycleServiceMixin,
    _AuthoringExamService,
):
    """Combined authoring/lifecycle facade with collaboration and timetable guards."""

    # ------------------------------------------------------------------
    # Lead-author coordination
    # ------------------------------------------------------------------

    @staticmethod
    def _actor_teacher_id(actor: LocalActor) -> UUID | None:
        if actor.role != "teacher":
            return None
        if actor.weave_membership_id is None:
            raise ExamAuthorizationError(
                "Teacher is missing a Weave membership identity"
            )
        try:
            return UUID(actor.weave_membership_id)
        except (TypeError, ValueError) as exc:
            raise ExamAuthorizationError(
                "Teacher has an invalid Weave membership identity"
            ) from exc

    @classmethod
    async def _eligible_lead_teachers_for_scope(
        cls,
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID,
        term_id: UUID,
    ) -> list:
        eligible_classes = await AcademicEligibilityService.list_eligible_classes(
            db,
            curriculum_subject_id=curriculum_subject_id,
            academic_term_id=term_id,
        )
        if not eligible_classes:
            raise AcademicScopeError(
                "Curriculum subject has no academically eligible classes "
                "for the selected academic term"
            )

        eligible_class_ids = {classroom.id for classroom in eligible_classes}
        assignments = await AcademicRepository.list_effective_teacher_assignments(db)
        teacher_ids = {
            assignment.teacher_membership_id
            for assignment in assignments
            if assignment.curriculum_subject_id == curriculum_subject_id
            and assignment.class_id in eligible_class_ids
        }
        return await AcademicRepository.list_teachers_by_ids(
            db,
            list(teacher_ids),
            active_only=True,
        )

    @classmethod
    async def _validate_lead_teacher(
        cls,
        db: AsyncSession,
        *,
        teacher_id: UUID,
        curriculum_subject_id: UUID,
        term_id: UUID,
    ) -> None:
        teachers = await cls._eligible_lead_teachers_for_scope(
            db,
            curriculum_subject_id=curriculum_subject_id,
            term_id=term_id,
        )
        if teacher_id not in {teacher.id for teacher in teachers}:
            raise AcademicAuthorizationError(
                "Selected lead teacher is not currently assigned to this "
                "curriculum subject in an academically eligible class for the term"
            )

    @classmethod
    async def list_eligible_lead_teachers(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        curriculum_subject_id: UUID,
        term_id: UUID,
    ) -> list:
        cls._require_admin(actor)
        return await cls._eligible_lead_teachers_for_scope(
            db,
            curriculum_subject_id=curriculum_subject_id,
            term_id=term_id,
        )

    @classmethod
    async def _resolve_initial_lead_teacher_id(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        payload: ExamCreate,
    ) -> UUID | None:
        requested = payload.lead_teacher_id
        if actor.role == "admin":
            if requested is not None:
                await cls._validate_lead_teacher(
                    db,
                    teacher_id=requested,
                    curriculum_subject_id=payload.curriculum_subject_id,
                    term_id=payload.term_id,
                )
            return requested

        if actor.role != "teacher":
            raise ExamAuthorizationError(
                "Only administrators and teachers can create examinations"
            )

        own_teacher_id = cls._actor_teacher_id(actor)
        assert own_teacher_id is not None
        if requested is not None and requested != own_teacher_id:
            raise ExamAuthorizationError(
                "Teacher-created examinations must use the creating teacher as lead author"
            )
        return own_teacher_id

    @staticmethod
    def _is_lead_or_admin(actor: LocalActor, exam: Exam) -> bool:
        if not actor.is_active:
            return False
        if actor.role == "admin":
            return True
        if actor.role != "teacher":
            return False

        try:
            teacher_id = (
                UUID(actor.weave_membership_id) if actor.weave_membership_id else None
            )
        except (TypeError, ValueError):
            return False

        lead_teacher_id = getattr(exam, "lead_teacher_id", None)
        if lead_teacher_id is not None:
            return teacher_id == lead_teacher_id

        # Explicit NULL leadership on rows using the new contract means the
        # administrator coordinates the paper. Only legacy/in-memory rows that
        # predate lead-assignment metadata fall back to creator-as-lead.
        if getattr(exam, "lead_assigned_at", None) is not None:
            return False
        return actor.id == exam.created_by_actor_id

    @staticmethod
    def _require_lead_or_admin(actor: LocalActor, exam: Exam) -> None:
        if not actor.is_active:
            raise ExamAuthorizationError("Active local actor is required")
        if ExamService._is_lead_or_admin(actor, exam):
            return
        raise ExamAuthorizationError(
            "Only the lead author or a school administrator can perform "
            "this shared-paper operation"
        )

    @staticmethod
    def _exam_creation_conflict_message(existing_exam: Exam) -> str:
        """Explain why an academic assessment scope cannot own a second lineage."""

        title = getattr(existing_exam, "title", None) or "Existing examination"
        prefix = (
            f'An examination ("{title}") already owns this term, curriculum '
            "subject and assessment component. "
        )
        status = existing_exam.status

        if status == ExamStatus.DRAFT:
            return (
                prefix + "It is still a draft. Open and continue editing the existing "
                "draft instead of creating another examination."
            )
        if status == ExamStatus.SUBMITTED:
            return (
                prefix
                + "It has already been submitted for review. Return the existing "
                "examination to draft if changes are needed; a second examination "
                "cannot be created for the same assessment component."
            )
        if status == ExamStatus.SEALED:
            return (
                prefix + "It has already been sealed as the official paper. Use the "
                "existing examination, or use the revision/replacement workflow "
                "if the paper must be replaced before the sitting."
            )
        if status == ExamStatus.ACTIVE:
            return (
                prefix + "That examination is currently active. Another examination "
                "cannot be created for the same assessment component while the "
                "official sitting is in progress."
            )
        if status == ExamStatus.SUSPENDED:
            return (
                prefix
                + "That examination is currently suspended. Resume or resolve the "
                "existing sitting instead of creating another examination for the "
                "same assessment component."
            )
        if status == ExamStatus.CLOSED:
            return (
                prefix + "It has already been conducted and closed. Use the existing "
                "makeup/late-start workflow for eligible missed candidates. If the "
                "completed exam must be replaced, its results must first be voided "
                "and the formal revision/replacement workflow used."
            )
        if status == ExamStatus.CANCELLED:
            return (
                prefix
                + "It was cancelled but its exam lineage is preserved for audit. "
                "Use the revision/replacement workflow to create the replacement "
                "paper instead of creating a separate examination."
            )

        return (
            prefix
            + "Only one official examination lineage is allowed for an assessment "
            "component in a term. Open the existing examination and continue from it."
        )

    @staticmethod
    def _schedule_utc(value: datetime | None, field_name: str) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ExamStateError(f"{field_name} must include a timezone")
        return value.astimezone(UTC)

    @classmethod
    def _require_authoring_schedule(
        cls,
        *,
        scheduled_start_at: datetime | None,
        latest_normal_start_at: datetime | None,
        require_scheduled: bool,
        action: str,
    ) -> None:
        """Validate the durable schedule at authoring lifecycle boundaries."""

        scheduled = cls._schedule_utc(scheduled_start_at, "scheduled_start_at")
        latest = cls._schedule_utc(
            latest_normal_start_at,
            "latest_normal_start_at",
        )

        if scheduled is None:
            if latest is not None:
                raise ExamStateError(
                    "Latest normal start cannot exist without a scheduled start"
                )
            if require_scheduled:
                raise ExamStateError(f"Schedule the examination before {action}.")
            return

        if scheduled <= datetime.now(UTC):
            raise ExamStateError(
                "The scheduled examination time has elapsed. "
                f"Reschedule the examination before {action}."
            )

        try:
            validate_normal_entry_window(scheduled, latest)
        except ValueError as exc:
            raise ExamStateError(str(exc)) from exc

    @classmethod
    async def assign_lead_teacher(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        lead_teacher_id: UUID | None,
        expected_authoring_version: int,
    ) -> Exam:
        """Change draft leadership without rewriting creator provenance.

        A NULL lead_teacher_id explicitly returns coordination to administration.
        Lead changes are draft-only so submitted/sealed evidence never changes
        ownership silently.
        """

        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.DRAFT:
            raise ExamStateError(
                "Lead author can only be changed while the examination is in DRAFT state"
            )
        cls._require_expected_authoring_version(exam, expected_authoring_version)

        if lead_teacher_id is not None:
            await cls._validate_lead_teacher(
                db,
                teacher_id=lead_teacher_id,
                curriculum_subject_id=exam.curriculum_subject_id,
                term_id=exam.term_id,
            )

        if (
            getattr(exam, "lead_teacher_id", None) == lead_teacher_id
            and getattr(exam, "lead_assigned_at", None) is not None
        ):
            await db.commit()
            return exam

        exam.lead_teacher_id = lead_teacher_id
        exam.lead_assigned_by_actor_id = actor.id
        exam.lead_assigned_at = datetime.now(UTC)
        cls._bump_authoring_version(exam)

        try:
            exam = await ExamRepository.save_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The examination lead could not be changed because the current "
                "paper conflicts with existing examination data"
            ) from exc
        return exam

    @classmethod
    async def _before_create_exam_save(
        cls,
        db: AsyncSession,
        *,
        payload: ExamCreate,
    ) -> None:
        await ExamTimetableService.require_planned_slot_available(
            db,
            session_id=payload.session_id,
            term_id=payload.term_id,
            curriculum_subject_id=payload.curriculum_subject_id,
            scheduled_start_at=payload.scheduled_start_at,
            latest_normal_start_at=payload.latest_normal_start_at,
            duration_minutes=payload.duration_minutes,
        )

    @classmethod
    async def _before_update_exam_save(
        cls,
        db: AsyncSession,
        *,
        exam: Exam,
        session_id: UUID,
        term_id: UUID,
        scheduled_start_at: datetime | None,
        duration_minutes: int,
    ) -> None:
        # The public update_exam preflight owns timetable validation because it
        # has the complete PATCH result, including latest_normal_start_at.
        lead_teacher_id = getattr(exam, "lead_teacher_id", None)
        if lead_teacher_id is not None:
            await cls._validate_lead_teacher(
                db,
                teacher_id=lead_teacher_id,
                curriculum_subject_id=exam.curriculum_subject_id,
                term_id=term_id,
            )

    @classmethod
    async def _before_activate_exam_save(cls, db: AsyncSession, *, exam: Exam) -> None:
        await ExamTimetableService.require_level_free(db, exam_id=exam.id)

    @classmethod
    async def _before_resume_exam_save(cls, db: AsyncSession, *, exam: Exam) -> None:
        await ExamTimetableService.require_level_free(db, exam_id=exam.id)

    @classmethod
    async def create_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        payload: ExamCreate,
    ) -> Exam:
        """Create the shared draft and its lead decision in one transaction."""

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

        existing_exam = await ExamRepository.get_exam_revision(
            db,
            term_id=payload.term_id,
            curriculum_subject_id=payload.curriculum_subject_id,
            assessment_component_id=payload.assessment_component_id,
            title=payload.title,
            revision_number=1,
        )
        if existing_exam is not None:
            raise ValueError(cls._exam_creation_conflict_message(existing_exam))

        lead_teacher_id = await cls._resolve_initial_lead_teacher_id(
            db,
            actor=actor,
            payload=payload,
        )
        await cls._before_create_exam_save(db, payload=payload)

        normalized_instructions = None
        if payload.instructions is not None:
            normalized_instructions = payload.instructions.strip() or None
        now = datetime.now(UTC)
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
            instructions=normalized_instructions,
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
            lead_teacher_id=lead_teacher_id,
            lead_assigned_by_actor_id=actor.id,
            lead_assigned_at=now,
            component_maximum_score=None,
        )

        try:
            exam = await ExamRepository.add_exam(db, exam)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            existing_exam = await ExamRepository.get_exam_revision(
                db,
                term_id=payload.term_id,
                curriculum_subject_id=payload.curriculum_subject_id,
                assessment_component_id=payload.assessment_component_id,
                revision_number=1,
            )
            if existing_exam is not None:
                raise ValueError(
                    cls._exam_creation_conflict_message(existing_exam)
                ) from exc
            raise ValueError(
                "The examination could not be created because another examination "
                "now owns this term, curriculum subject and assessment component. "
                "Refresh the examinations page and continue from the existing paper."
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

        fields = payload.model_fields_set
        if (
            "scheduled_start_at" in fields
            and payload.scheduled_start_at is None
            and "latest_normal_start_at" not in fields
        ):
            payload_data = payload.model_dump(exclude_unset=True)
            payload_data["latest_normal_start_at"] = None
            payload = ExamUpdate.model_validate(payload_data)
            fields = payload.model_fields_set

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
        next_session_id = (
            payload.session_id if "session_id" in fields else exam.session_id
        )
        next_term_id = payload.term_id if "term_id" in fields else exam.term_id
        next_duration_minutes = (
            payload.duration_minutes
            if "duration_minutes" in fields
            else exam.duration_minutes
        )

        cls._require_authoring_schedule(
            scheduled_start_at=next_scheduled_start_at,
            latest_normal_start_at=next_latest_normal_start_at,
            require_scheduled=False,
            action="saving changes to this draft",
        )
        await ExamTimetableService.require_planned_slot_available(
            db,
            session_id=next_session_id,
            term_id=next_term_id,
            curriculum_subject_id=exam.curriculum_subject_id,
            scheduled_start_at=next_scheduled_start_at,
            latest_normal_start_at=next_latest_normal_start_at,
            duration_minutes=next_duration_minutes,
            exclude_exam_id=exam.id,
        )

        return await super().update_exam(
            db, actor=actor, payload=payload, exam_id=exam_id
        )

    @classmethod
    async def submit_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        expected_authoring_version: int = 1,
    ) -> Exam:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
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
        cls._require_authoring_schedule(
            scheduled_start_at=exam.scheduled_start_at,
            latest_normal_start_at=exam.latest_normal_start_at,
            require_scheduled=True,
            action="submitting it for review",
        )
        await ExamTimetableService.require_planned_slot_available(
            db,
            session_id=exam.session_id,
            term_id=exam.term_id,
            curriculum_subject_id=exam.curriculum_subject_id,
            scheduled_start_at=exam.scheduled_start_at,
            latest_normal_start_at=exam.latest_normal_start_at,
            duration_minutes=exam.duration_minutes,
            exclude_exam_id=exam.id,
        )
        return await super().submit_exam(
            db,
            actor=actor,
            exam_id=exam_id,
            expected_authoring_version=expected_authoring_version,
        )

    @classmethod
    async def remove_manual_question(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        payload: ManualQuestionRemove,
    ) -> Exam:
        """Allow contributors to remove their own question; lead/admin may remove any."""

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
            not cls._is_lead_or_admin(actor, exam)
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
                "The manual question selection could not be updated because "
                "it conflicts with existing examination data"
            ) from exc
        return exam

    @classmethod
    async def seal_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.SUBMITTED:
            raise ExamStateError("Only examinations in SUBMITTED state can be sealed")
        cls._require_admin(actor)
        cls._require_authoring_schedule(
            scheduled_start_at=exam.scheduled_start_at,
            latest_normal_start_at=exam.latest_normal_start_at,
            require_scheduled=True,
            action="sealing it",
        )
        await ExamTimetableService.require_planned_slot_available(
            db,
            session_id=exam.session_id,
            term_id=exam.term_id,
            curriculum_subject_id=exam.curriculum_subject_id,
            scheduled_start_at=exam.scheduled_start_at,
            latest_normal_start_at=exam.latest_normal_start_at,
            duration_minutes=exam.duration_minutes,
            exclude_exam_id=exam.id,
        )
        return await super().seal_exam(db, actor=actor, exam_id=exam_id)

    @classmethod
    async def activate_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        return await super().activate_exam(db, actor=actor, exam_id=exam_id)

    @classmethod
    async def resume_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        reason: str | None = None,
    ) -> Exam:
        return await super().resume_exam(
            db, actor=actor, exam_id=exam_id, reason=reason
        )

    @staticmethod
    async def _preflight_suspended_terminal_transition(
        db: AsyncSession,
        *,
        exam: Exam,
        operation: str,
    ) -> None:
        if exam.status != ExamStatus.SUSPENDED:
            return
        suspension = await ExamRepository.get_open_suspension_for_exam(
            db,
            exam.id,
            lock=True,
        )
        if suspension is None:
            raise ExamStateError("Suspended examination has no open suspension record")
        # Flush the locked row before staging terminal state. Besides validating
        # the durable suspension row, this preserves the old all-or-nothing
        # behavior if its persistence is inconsistent.
        try:
            await ExamRepository.save_suspension(db, suspension)
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(f"The examination could not be {operation}") from exc

    @classmethod
    async def close_exam(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        current = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if current is None:
            raise ExamNotFound("Examination does not exist")
        await cls._preflight_suspended_terminal_transition(
            db,
            exam=current,
            operation="closed",
        )
        exam = await ExamExecutionService.request_close(
            db,
            actor=actor,
            exam_id=exam_id,
        )
        await arq_producer.enqueue("finalize_exam_close", str(exam.id))
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
        current = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if current is None:
            raise ExamNotFound("Examination does not exist")
        await cls._preflight_suspended_terminal_transition(
            db,
            exam=current,
            operation="cancelled",
        )
        exam = await ExamExecutionService.request_cancel(
            db,
            actor=actor,
            exam_id=exam_id,
            reason=reason,
        )
        await arq_producer.enqueue("finalize_exam_cancellation", str(exam.id))
        return exam

    @classmethod
    async def _create_voided_closed_revision(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        latest: Exam,
    ) -> Exam:
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
            folder_color=latest.folder_color,
            duration_minutes=latest.duration_minutes,
            shuffle_questions=latest.shuffle_questions,
            shuffle_options=latest.shuffle_options,
            scheduled_start_at=None,
            latest_normal_start_at=None,
            status=ExamStatus.DRAFT,
            roster_status=ExamRosterStatus.NOT_PREPARED,
            roster_version=0,
            roster_candidate_count=0,
            revision_number=latest.revision_number + 1,
            revision_of_exam_id=latest.id,
            created_by_actor_id=actor.id,
            lead_teacher_id=getattr(latest, "lead_teacher_id", None),
            lead_assigned_by_actor_id=actor.id,
            lead_assigned_at=datetime.now(UTC),
            component_maximum_score=None,
        )

        try:
            revision = await ExamRepository.add_exam(db, revision)
            if revision.question_selection_mode == ExamQuestionSelectionMode.MANUAL:
                frozen_questions = await ExamRepository.list_exam_questions(
                    db, latest.id
                )
                if any(
                    question.added_by_actor_id is None for question in frozen_questions
                ):
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
    async def create_revision(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        latest = await cls._latest_revision_in_lineage(db, exam)

        if latest.status == ExamStatus.CLOSED:
            if not await ExamExecutionService.results_are_voided(db, exam_id=latest.id):
                raise ExamStateError(
                    "A CLOSED examination can only be revised after its results are voided"
                )
        elif latest.status not in {ExamStatus.SEALED, ExamStatus.CANCELLED}:
            raise ExamStateError(
                "A new revision can only be created from the latest SEALED "
                "or CANCELLED examination revision, or a CLOSED revision with VOIDED results"
            )

        # Every replacement is a new sitting. Preserve the paper configuration
        # and lineage, but require its timetable to be chosen deliberately.
        return await cls._create_voided_closed_revision(
            db,
            actor=actor,
            latest=latest,
        )

    @staticmethod
    async def get_exam(
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> Exam:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if not actor.is_active:
            raise ExamAuthorizationError("Active local actor is required")
        if actor.role == "admin":
            return exam
        if actor.role != "teacher":
            raise ExamAuthorizationError("You are not allowed to view this examination")
        if exam.created_by_actor_id == actor.id:
            try:
                await AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                    db,
                    actor=actor,
                    curriculum_subject_id=exam.curriculum_subject_id,
                    academic_term_id=exam.term_id,
                )
            except AcademicAuthorizationError as exc:
                raise ExamAuthorizationError(
                    "You are not allowed to view this examination"
                ) from exc
            return exam

        teacher_membership_id: UUID | None = None
        if actor.weave_membership_id is not None:
            try:
                teacher_membership_id = UUID(actor.weave_membership_id)
            except ValueError as exc:
                raise ExamAuthorizationError(
                    "Teacher has an invalid Weave membership identity"
                ) from exc
        if teacher_membership_id is not None:
            invigilator = await ExamRepository.get_invigilator(
                db,
                exam.id,
                teacher_membership_id,
            )
            if invigilator is not None:
                return exam

        try:
            await AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
                academic_term_id=exam.term_id,
            )
        except AcademicAuthorizationError as exc:
            raise ExamAuthorizationError(
                "You are not allowed to view this examination"
            ) from exc
        return exam


__all__ = ["ExamService"]
