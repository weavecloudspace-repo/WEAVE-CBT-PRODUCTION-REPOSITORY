"""Lifecycle-aware attempt facade used by HTTP routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.attempts.models import (
    AttemptEndReason,
    AttemptInterruption,
    AttemptStatus,
    ExamAttempt,
)
from app.domains.attempts.repository import AttemptRepository
from app.domains.attempts.schemas import (
    AttemptBulkOperatorResponse,
    AttemptHeartbeatResponse,
    AttemptSubmissionResponse,
)
from app.domains.attempts.service import AttemptService as _AttemptService
from app.domains.attempts.service import AttemptStateError
from app.domains.auth.models import LocalActor
from app.domains.auth.student_service import StudentSessionContext
from app.domains.candidates.models import CandidateStatus
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.exceptions import ExamNotFound
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.models import Exam, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.results.repository import ResultRepository
from app.workers.producer import arq_producer

_FINALIZING_STATES = {ExamStatus.CLOSING, ExamStatus.CANCELLING}
ATTEMPT_HEARTBEAT_RECOMMENDED_INTERVAL_SECONDS = 20


class AttemptService(_AttemptService):
    """Apply whole-exam lifecycle guards around the core attempt service."""

    @staticmethod
    async def _effective_late_start_deadline(exam: Exam) -> datetime | None:
        # Legacy NULL rows mean zero configured grace, not unlimited entry. This
        # matches timetable planning and the roster control surface.
        deadline = exam.latest_normal_start_at or exam.scheduled_start_at
        if deadline is None:
            return None
        if (
            exam.scheduled_start_at is not None
            and exam.activated_at is not None
            and exam.activated_at > exam.scheduled_start_at
        ):
            deadline = deadline + (exam.activated_at - exam.scheduled_start_at)
        return deadline

    @classmethod
    async def _validate_normal_start(
        cls,
        db: AsyncSession,
        *,
        candidate,
        exam: Exam,
        now: datetime,
    ):
        if exam.status != ExamStatus.ACTIVE:
            raise AttemptStateError("Normal examination is not active")
        if candidate.status != CandidateStatus.ELIGIBLE:
            raise AttemptStateError(
                "Candidate is not eligible to start this examination"
            )

        deadline = await cls._effective_late_start_deadline(exam)
        if deadline is None or now <= deadline:
            return None

        authorization = await CandidateRepository.get_usable_late_start_authorization(
            db,
            candidate.id,
            at=now,
            lock=True,
        )
        if authorization is None:
            raise AttemptStateError(
                "Candidate requires a valid late-start authorization"
            )
        return authorization

    @classmethod
    async def _build_finalizing_response(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ):
        attempt, candidate, exam = await cls._get_current_attempt(
            db,
            context=context,
            lock=True,
        )
        control = await ExamExecutionRepository.get_control(db, exam.id)
        if control is None or control.operation_requested_at is None:
            raise AttemptStateError("Examination finalization metadata is unavailable")

        response = await cls._build_attempt_response(
            db,
            attempt=attempt,
            candidate=candidate,
            exam=exam,
            is_makeup=context.is_makeup,
        )
        response.exam_suspended = True
        response.remaining_seconds = await cls.remaining_seconds(
            db,
            attempt=attempt,
            exam_id=exam.id,
            at=control.operation_requested_at,
        )
        return response

    @classmethod
    async def heartbeat_current(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ) -> AttemptHeartbeatResponse:
        """Record candidate-device liveness without changing attempt state.

        Missing heartbeats remain monitoring evidence only. Deterministic timer
        expiry is finalized by the timeout recovery worker, not inferred from
        network connectivity.
        """

        attempt, _candidate, exam = await cls._get_current_attempt(
            db,
            context=context,
            lock=False,
        )
        if attempt.status not in {
            AttemptStatus.IN_PROGRESS,
            AttemptStatus.INTERRUPTED,
        }:
            raise AttemptStateError("Ended attempts do not accept heartbeats")

        if not context.is_makeup and exam.status not in {
            ExamStatus.ACTIVE,
            ExamStatus.SUSPENDED,
        }:
            raise AttemptStateError(
                "Examination finalization has started and no longer accepts candidate heartbeats"
            )

        now = datetime.now(UTC)
        attempt.last_heartbeat_at = now
        await AttemptRepository.save_attempt(db, attempt)
        await db.commit()

        remaining = await cls.remaining_seconds(
            db,
            attempt=attempt,
            exam_id=exam.id,
            at=now,
        )
        return AttemptHeartbeatResponse(
            attempt_id=attempt.id,
            status=attempt.status,
            server_time=now,
            last_heartbeat_at=now,
            remaining_seconds=remaining,
            exam_suspended=(
                exam.status == ExamStatus.SUSPENDED and not context.is_makeup
            ),
            next_heartbeat_after_seconds=ATTEMPT_HEARTBEAT_RECOMMENDED_INTERVAL_SECONDS,
        )

    @classmethod
    async def get_current(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ):
        if not context.is_makeup:
            _candidate, exam = await cls._get_candidate_and_exam(
                db,
                context=context,
                lock=False,
            )
            if exam.status in _FINALIZING_STATES:
                await db.rollback()
                return await cls._build_finalizing_response(db, context=context)
            await db.rollback()
        return await super().get_current(db, context=context)

    @classmethod
    async def get_current_result(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ) -> AttemptSubmissionResponse:
        """Return the immutable score for the exact submitted student attempt."""

        attempt, _candidate, exam = await cls._get_current_attempt(
            db,
            context=context,
            lock=False,
        )
        if attempt.status != AttemptStatus.SUBMITTED:
            raise AttemptStateError("Candidate examination attempt is not completed")

        result = await ResultRepository.get_result_by_attempt_id(db, attempt.id)
        if result is None:
            raise AttemptStateError("Submitted attempt is missing its result")

        return AttemptSubmissionResponse(
            voided_at=result.voided_at,
            subject_name=await cls._exam_subject_name(db, exam),
            attempt_id=attempt.id,
            status=attempt.status,
            end_reason=attempt.end_reason,
            ended_at=attempt.ended_at,
            result_id=result.id,
            raw_score=result.raw_score,
            raw_max_score=result.raw_max_score,
            percentage=str(result.percentage),
            component_score=str(result.component_score),
            component_maximum_score=str(result.component_maximum_score),
        )

    @classmethod
    async def start_current(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ):
        if not context.is_makeup:
            candidate, exam = await cls._get_candidate_and_exam(
                db,
                context=context,
                lock=False,
            )
            if exam.status in _FINALIZING_STATES:
                existing = await AttemptRepository.get_attempt_by_candidate_id(
                    db,
                    candidate.id,
                )
                await db.rollback()
                if existing is None:
                    raise AttemptStateError(
                        "Examination finalization has started; no new attempts may begin"
                    )
                return await cls._build_finalizing_response(db, context=context)
            await db.rollback()
        return await super().start_current(db, context=context)

    @classmethod
    async def submit_current(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ):
        _attempt, _candidate, exam = await cls._get_current_attempt(
            db,
            context=context,
            lock=False,
        )
        if not context.is_makeup and exam.status in {
            ExamStatus.CLOSING,
            ExamStatus.CANCELLING,
            ExamStatus.CANCELLED,
        }:
            await db.rollback()
            raise AttemptStateError(
                "Examination is being finalized and cannot be submitted by the candidate"
            )
        await db.rollback()
        result = await super().submit_current(db, context=context)
        if context.exam_id is not None and not context.is_makeup:
            await arq_producer.enqueue("evaluate_exam_completion", str(context.exam_id))
        return result

    @classmethod
    async def interrupt_attempt(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        attempt_id: UUID,
        reason: str,
    ):
        attempt = await AttemptRepository.get_attempt_by_id(db, attempt_id)
        if attempt is None:
            raise AttemptStateError("Attempt does not exist")
        candidate = await CandidateRepository.get_candidate_by_id(
            db, attempt.candidate_id
        )
        if candidate is None:
            raise AttemptStateError("Attempt candidate does not exist")
        exam = await ExamRepository.get_exam_by_id(db, exam_id=candidate.exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.ACTIVE:
            await db.rollback()
            raise AttemptStateError(
                "Candidate attempts can only be interrupted while the examination is active"
            )
        await db.rollback()
        return await super().interrupt_attempt(
            db,
            actor=actor,
            attempt_id=attempt_id,
            reason=reason,
        )

    @classmethod
    async def bulk_interrupt_attempts(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        attempt_ids: list[UUID],
        reason: str,
    ) -> AttemptBulkOperatorResponse:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason is required")
        ids = list(dict.fromkeys(attempt_ids))
        if not ids:
            raise ValueError("Select at least one attempt")

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.ACTIVE:
            raise AttemptStateError(
                "Candidate attempts can only be interrupted while the examination is active"
            )
        await cls._require_operator(db, actor=actor, exam_id=exam.id)

        attempts = list(
            (
                await db.execute(
                    select(ExamAttempt)
                    .where(ExamAttempt.id.in_(ids))
                    .order_by(ExamAttempt.id.asc())
                    .with_for_update(of=ExamAttempt)
                )
            )
            .scalars()
            .all()
        )
        if len(attempts) != len(ids):
            raise AttemptStateError("One or more selected attempts do not exist")
        if any(attempt.status != AttemptStatus.IN_PROGRESS for attempt in attempts):
            raise AttemptStateError("Only in-progress attempts can be interrupted")

        candidate_ids = [attempt.candidate_id for attempt in attempts]
        candidates = await CandidateRepository.list_candidates_by_ids(db, candidate_ids)
        candidate_by_id = {candidate.id: candidate for candidate in candidates}
        if len(candidate_by_id) != len(candidate_ids) or any(
            candidate_by_id[attempt.candidate_id].exam_id != exam.id
            for attempt in attempts
        ):
            raise AttemptStateError(
                "One or more selected attempts do not belong to this examination"
            )

        now = datetime.now(UTC)
        interruptions: list[AttemptInterruption] = []
        for attempt in attempts:
            await cls._checkpoint_active_segment(
                db,
                attempt=attempt,
                exam_id=exam.id,
                at=now,
            )
            remaining = max(0, attempt.time_limit_seconds - attempt.elapsed_seconds)
            if remaining <= 0:
                await db.rollback()
                raise AttemptStateError(
                    "One or more selected attempts have no remaining writing time"
                )
            attempt.status = AttemptStatus.INTERRUPTED
            interruptions.append(
                AttemptInterruption(
                    attempt_id=attempt.id,
                    interrupted_at=now,
                    remaining_seconds=remaining,
                    reason=normalized_reason,
                )
            )

        try:
            db.add_all(interruptions)
            for attempt in attempts:
                db.add(attempt)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise AttemptStateError("Selected attempts could not be interrupted") from exc

        return AttemptBulkOperatorResponse(
            action="interrupt",
            updated_count=len(attempts),
            attempt_ids=ids,
        )

    @classmethod
    async def resume_attempt(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        attempt_id: UUID,
        reason: str,
    ):
        return await super().resume_attempt(
            db,
            actor=actor,
            attempt_id=attempt_id,
            reason=reason,
        )

    @classmethod
    async def terminate_attempt(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        attempt_id: UUID,
        reason: str,
    ):
        attempt = await AttemptRepository.get_attempt_by_id(db, attempt_id)
        if attempt is None:
            raise AttemptStateError("Attempt does not exist")
        candidate = await CandidateRepository.get_candidate_by_id(
            db, attempt.candidate_id
        )
        if candidate is None:
            raise AttemptStateError("Attempt candidate does not exist")
        exam = await ExamRepository.get_exam_by_id(db, exam_id=candidate.exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status not in {ExamStatus.ACTIVE, ExamStatus.SUSPENDED}:
            await db.rollback()
            raise AttemptStateError(
                "Candidate attempts cannot be terminated after exam finalization starts"
            )
        await db.rollback()
        response = await super().terminate_attempt(
            db,
            actor=actor,
            attempt_id=attempt_id,
            reason=reason,
        )
        await arq_producer.enqueue("evaluate_exam_completion", str(candidate.exam_id))
        return response

    @classmethod
    async def finalize_if_expired(
        cls,
        db: AsyncSession,
        *,
        attempt_id: UUID,
        at: datetime | None = None,
    ) -> UUID | None:
        """Finalize one objectively expired attempt without a browser request.

        Returns the normal exam ID when automatic completion should be
        re-evaluated. Makeup attempts share the same timer but do not drive the
        original closed examination lifecycle.
        """

        attempt = await AttemptRepository.get_attempt_by_id(db, attempt_id, lock=True)
        if attempt is None or attempt.status != AttemptStatus.IN_PROGRESS:
            await db.rollback()
            return None

        candidate = await CandidateRepository.get_candidate_by_id(
            db,
            attempt.candidate_id,
            lock=True,
        )
        if candidate is None:
            await db.rollback()
            return None
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=candidate.exam_id,
            lock=True,
        )
        if exam is None:
            await db.rollback()
            return None

        is_makeup = await cls._is_makeup_candidate(db, candidate.id)
        if not is_makeup and exam.status not in {
            ExamStatus.ACTIVE,
            ExamStatus.SUSPENDED,
        }:
            await db.rollback()
            return None

        now = at or datetime.now(UTC)
        remaining = await cls.remaining_seconds(
            db,
            attempt=attempt,
            exam_id=exam.id,
            at=now,
        )
        if remaining > 0:
            await db.rollback()
            return None

        await cls._submit_locked(
            db,
            attempt=attempt,
            candidate=candidate,
            exam=exam,
            end_reason=AttemptEndReason.TIME_EXPIRED,
            revoke_reason="Examination time expired",
        )
        return None if is_makeup else exam.id
