"""Scoring and read services for locally calculated CBT results."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError
from app.domains.academics.authorization import AcademicAuthorizationService
from app.domains.attempts.models import AttemptStatus, ExamAttempt
from app.domains.attempts.repository import AttemptRepository
from app.domains.audit.models import AuditActorType, AuditEvent
from app.domains.audit.repository import AuditRepository
from app.domains.auth.models import LocalActor
from app.domains.candidates.models import ExamCandidate
from app.domains.exams.exceptions import ExamNotFound, ExamStateError
from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.models import Exam, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.results.models import ExamResult, ResultSyncStatus
from app.domains.results.query_repository import ResultQueryRepository
from app.domains.results.repository import ResultRepository

_TWO_DP = Decimal("0.01")


class ResultService:
    @staticmethod
    async def calculate_for_submitted_attempt(
        db: AsyncSession,
        *,
        attempt: ExamAttempt,
        candidate,
        exam: Exam,
    ) -> ExamResult:
        """Calculate exactly once from immutable attempt paper/answer snapshots."""
        if attempt.status != AttemptStatus.SUBMITTED:
            raise ValueError("Only submitted attempts can produce a result")
        existing = await ResultRepository.get_result_by_attempt_id(
            db, attempt.id, lock=True
        )
        if existing is not None:
            return existing
        if exam.component_maximum_score is None:
            raise ValueError("Examination is missing its frozen component maximum")

        questions = await AttemptRepository.list_question_allocations(db, attempt.id)
        if not questions:
            raise ValueError("Attempt has no allocated questions")
        options = await AttemptRepository.list_option_allocations_for_questions(
            db, [question.id for question in questions]
        )
        answers = await AttemptRepository.list_answers_for_attempt(db, attempt.id)
        selections = await AttemptRepository.list_selections_for_answers(
            db, [answer.id for answer in answers]
        )

        correct_by_question: dict[UUID, set[UUID]] = defaultdict(set)
        for option in options:
            if option.is_correct:
                correct_by_question[option.attempt_question_id].add(option.id)

        answer_by_question = {answer.attempt_question_id: answer for answer in answers}
        selected_by_answer: dict[UUID, set[UUID]] = defaultdict(set)
        for selection in selections:
            selected_by_answer[selection.answer_id].add(selection.attempt_option_id)

        raw_score = 0
        for question in questions:
            answer = answer_by_question.get(question.id)
            selected = selected_by_answer.get(answer.id, set()) if answer else set()
            correct = correct_by_question.get(question.id, set())
            if correct and selected == correct:
                raw_score += 1

        raw_max = len(questions)
        percentage = (Decimal(raw_score) * Decimal(100) / Decimal(raw_max)).quantize(
            _TWO_DP, rounding=ROUND_HALF_UP
        )
        component_max = Decimal(exam.component_maximum_score)
        component_score = (
            Decimal(raw_score) * component_max / Decimal(raw_max)
        ).quantize(_TWO_DP, rounding=ROUND_HALF_UP)

        timestamp = (
            attempt.started_at
            if exam.status == ExamStatus.CLOSED
            else (exam.activated_at or exam.scheduled_start_at or exam.closed_at)
        )
        if timestamp is None:
            raise ValueError("Examination result has no usable assessment date")
        result = ExamResult(
            exam_date=timestamp.date(),
            attempt_id=attempt.id,
            candidate_id=candidate.id,
            exam_id=exam.id,
            assessment_component_id=exam.assessment_component_id,
            raw_score=raw_score,
            raw_max_score=raw_max,
            percentage=percentage,
            component_score=component_score,
            component_maximum_score=component_max,
            calculated_at=datetime.now(UTC),
            sync_status=ResultSyncStatus.PENDING,
            sync_batch_id=None,
            sync_attempts=0,
        )
        # A score created after the sitting closed must receive a new review.
        # Previous approval is not permission to publish a future makeup score.
        if exam.status == ExamStatus.CLOSED:
            control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
            if (
                control is not None
                and control.result_disposition == ExamResultDisposition.APPROVED
            ):
                await AuditRepository.add_event(
                    db,
                    AuditEvent(
                        actor_type=AuditActorType.SYSTEM,
                        action="exam.results_review_reopened",
                        entity_type="exam",
                        entity_id=exam.id,
                        metadata_json={
                            "attempt_id": str(attempt.id),
                            "previous_decided_at": control.results_decided_at.isoformat()
                            if control.results_decided_at
                            else None,
                            "previous_decided_by_actor_id": str(
                                control.results_decided_by_actor_id
                            )
                            if control.results_decided_by_actor_id
                            else None,
                        },
                        reason="A new makeup result requires administrator review",
                    ),
                )
                control.result_disposition = ExamResultDisposition.PENDING_REVIEW
                control.results_decided_at = None
                control.results_decided_by_actor_id = None
                control.results_decision_reason = None
                await ExamExecutionRepository.save_control(db, control)
        # The caller owns rollback if the unique attempt/candidate constraints
        # reject a concurrent duplicate; never create an alternative score.
        return await ResultRepository.add_result(db, result)

    @staticmethod
    async def _require_can_view_exam_results(
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> None:
        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        if actor.role == "admin":
            return

        if actor.role != "teacher" or actor.weave_membership_id is None:
            raise AcademicAuthorizationError(
                "Administrator, invigilator, or authorized subject-teacher access is required"
            )

        try:
            teacher_id = UUID(actor.weave_membership_id)
        except ValueError as exc:
            raise AcademicAuthorizationError(
                "Teacher has an invalid Weave membership identity"
            ) from exc

        invigilator = await ExamRepository.get_invigilator(db, exam.id, teacher_id)
        if invigilator is not None:
            return

        try:
            await AcademicAuthorizationService.require_can_author_curriculum_subject_for_term(
                db,
                actor=actor,
                curriculum_subject_id=exam.curriculum_subject_id,
                academic_term_id=exam.term_id,
            )
        except AcademicAuthorizationError as exc:
            raise AcademicAuthorizationError(
                "Only assigned invigilators or currently authorized subject teachers "
                "may view these results"
            ) from exc

    @staticmethod
    def _require_admin(actor: LocalActor) -> None:
        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")
        if actor.role != "admin":
            raise AcademicAuthorizationError("Administrator access is required")

    @classmethod
    async def void_result(
        cls, db: AsyncSession, *, actor: LocalActor, result_id: UUID, reason: str
    ) -> ExamResult:
        return await cls._set_result_void(
            db, actor=actor, result_id=result_id, reason=reason, voided=True
        )

    @classmethod
    async def restore_result(
        cls, db: AsyncSession, *, actor: LocalActor, result_id: UUID, reason: str
    ) -> ExamResult:
        return await cls._set_result_void(
            db, actor=actor, result_id=result_id, reason=reason, voided=False
        )

    @classmethod
    async def _set_result_void(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        result_id: UUID,
        reason: str,
        voided: bool,
    ) -> ExamResult:
        cls._require_admin(actor)
        reason = reason.strip()
        if not reason or len(reason) > 1024:
            raise ValueError("Provide a reason of 1 to 1024 characters")
        result = await ResultRepository.get_result_by_id(db, result_id)
        if result is None:
            raise ValueError("Result does not exist")
        # Match the worker lock order: exam, control, result. Whichever commits first
        # determines whether this score is excluded or has entered a durable batch.
        exam = await ExamRepository.get_exam_by_id(
            db, exam_id=result.exam_id, lock=True
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.CLOSED:
            raise ExamStateError(
                "Individual results can only be voided after the examination closes"
            )
        control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
        if control is not None and (
            control.operation is not None
            or control.result_disposition == ExamResultDisposition.VOIDED
        ):
            raise ExamStateError(
                "This result set is voided or is still being finalized"
            )
        result = await ResultRepository.get_result_by_id(db, result_id, lock=True)
        if (result.voided_at is not None) == voided:
            raise ExamStateError(
                "This result is already voided"
                if voided
                else "Only an individually voided result can be restored"
            )
        if result.sync_batch_id is not None or result.sync_status not in (
            ResultSyncStatus.PENDING,
            ResultSyncStatus.FAILED,
        ):
            raise ExamStateError(
                "This result has entered synchronization. Resolve it in Weave before making a correction"
            )
        previous_void = {
            "voided_at": result.voided_at.isoformat()
            if result.voided_at is not None
            else None,
            "voided_by_actor_id": str(result.voided_by_actor_id)
            if result.voided_by_actor_id
            else None,
            "reason": result.void_reason,
        }
        result.voided_at = datetime.now(UTC) if voided else None
        result.voided_by_actor_id = actor.id if voided else None
        result.void_reason = reason if voided else None
        await ResultRepository.save_result(db, result)
        await AuditRepository.add_event(
            db,
            AuditEvent(
                actor_type=AuditActorType.LOCAL_ACTOR,
                actor_id=actor.id,
                actor_role=actor.role,
                action="result.voided" if voided else "result.void_restored",
                entity_type="exam_result",
                entity_id=result.id,
                reason=reason,
                metadata_json={"exam_id": str(exam.id), "previous_void": previous_void},
            ),
        )
        await db.commit()
        return result

    @classmethod
    async def get_result(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        result_id: UUID,
    ) -> ExamResult:
        result = await ResultRepository.get_result_by_id(db, result_id)
        if result is None:
            raise ValueError("Result does not exist")
        await cls._require_can_view_exam_results(
            db, actor=actor, exam_id=result.exam_id
        )
        return result

    @classmethod
    async def list_exam_results(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[ExamResult], int]:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        await cls._require_can_view_exam_results(db, actor=actor, exam_id=exam.id)
        rows = await ResultRepository.list_results_for_exam(
            db, exam.id, offset=offset, limit=limit
        )
        total = await ResultRepository.count_results_for_exam(db, exam.id)
        return rows, total

    @classmethod
    async def list_exam_result_review_rows(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        search: str | None = None,
        sync_status: ResultSyncStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[ExamResult, ExamCandidate]], int]:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        await cls._require_can_view_exam_results(db, actor=actor, exam_id=exam.id)
        rows = await ResultQueryRepository.list_exam_result_rows(
            db,
            exam_id=exam.id,
            search=search,
            sync_status=sync_status,
            offset=offset,
            limit=limit,
        )
        total = await ResultQueryRepository.count_exam_result_rows(
            db,
            exam_id=exam.id,
            search=search,
            sync_status=sync_status,
        )
        return rows, total

    @classmethod
    async def list_result_review_sets(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
    ) -> list[dict]:
        cls._require_admin(actor)
        return await ResultQueryRepository.list_review_sets(db)
