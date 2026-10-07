"""Durable examination completion, cancellation and result-review orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError
from app.domains.attempts.models import AttemptEndReason, AttemptStatus, ExamAttempt
from app.domains.attempts.repository import AttemptRepository
from app.domains.attempts.service import AttemptService
from app.domains.auth.models import LocalActor
from app.domains.auth.student_repository import StudentAuthRepository
from app.domains.candidates.models import (
    CandidateLateStartAuthorization,
    CandidateStatus,
    ExamCandidate,
)
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.exceptions import ExamNotFound, ExamStateError
from app.domains.exams.execution_models import (
    EXECUTION_ERROR_MAX_LENGTH,
    ExamExecutionControl,
    ExamExecutionOperation,
    ExamOperationSource,
    ExamResultDisposition,
)
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.models import (
    Exam,
    ExamStatus,
    ExamSuspension,
    ExamSuspensionSource,
)
from app.domains.exams.repository import ExamRepository
from app.domains.results.models import ExamResult, ResultSyncStatus
from app.domains.results.service import ResultService
from app.domains.runtime.models import RealtimeOutboxEvent
from app.domains.runtime.repository import RuntimeRepository

FINALIZATION_BATCH_SIZE = 200


class ExamExecutionService:
    """Own terminal exam transitions and the academic result-acceptance boundary."""

    @staticmethod
    def _require_admin(actor: LocalActor) -> None:
        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")
        if actor.role != "admin":
            raise AcademicAuthorizationError("Administrator access is required")

    @staticmethod
    def _require_reason(reason: str) -> str:
        value = reason.strip()
        if not value:
            raise ValueError("reason is required")
        return value

    @staticmethod
    async def _add_event(
        db: AsyncSession,
        *,
        exam_id: UUID,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        await RuntimeRepository.add_outbox_event(
            db,
            RealtimeOutboxEvent(
                aggregate_type="exam",
                aggregate_id=exam_id,
                event_type=event_type,
                payload=payload or {},
            ),
        )

    @classmethod
    async def _request_close(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
        actor: LocalActor | None,
        source: ExamOperationSource,
        reason: str | None,
        requested_at: datetime | None = None,
    ) -> Exam:
        if actor is not None:
            cls._require_admin(actor)
        elif source != ExamOperationSource.AUTOMATIC:
            raise AcademicAuthorizationError(
                "Automatic examination closure requires the automatic source"
            )

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        control = await ExamExecutionRepository.get_or_create_control(
            db, exam.id, lock=True
        )
        if control.operation == ExamExecutionOperation.CLOSING:
            await db.commit()
            return exam
        if control.operation is not None:
            raise ExamStateError(
                "Examination already has a terminal operation in progress"
            )
        if exam.status not in {ExamStatus.ACTIVE, ExamStatus.SUSPENDED}:
            raise ExamStateError("Only ACTIVE or SUSPENDED examinations can be closed")

        now = requested_at or datetime.now(UTC)
        control.operation = ExamExecutionOperation.CLOSING
        control.operation_source = source
        control.operation_requested_at = now
        control.operation_requested_by_actor_id = (
            actor.id if actor is not None else None
        )
        control.operation_reason = reason.strip() if reason and reason.strip() else None
        control.operation_error = None
        exam.status = ExamStatus.CLOSING

        await ExamExecutionRepository.save_control(db, control)
        await ExamRepository.save_exam(db, exam)
        await cls._add_event(
            db,
            exam_id=exam.id,
            event_type="exam.closing",
            payload={"source": source.value},
        )
        await db.commit()
        return exam

    @classmethod
    async def request_close(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        reason: str | None = None,
    ) -> Exam:
        return await cls._request_close(
            db,
            exam_id=exam_id,
            actor=actor,
            source=ExamOperationSource.ADMIN,
            reason=reason,
        )

    @classmethod
    async def request_automatic_close(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
        requested_at: datetime | None = None,
    ) -> Exam:
        return await cls._request_close(
            db,
            exam_id=exam_id,
            actor=None,
            source=ExamOperationSource.AUTOMATIC,
            reason="All candidates have completed or can no longer start normally",
            requested_at=requested_at,
        )

    @classmethod
    async def request_cancel(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        reason: str,
    ) -> Exam:
        cls._require_admin(actor)
        normalized_reason = cls._require_reason(reason)

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        control = await ExamExecutionRepository.get_or_create_control(
            db, exam.id, lock=True
        )
        if control.operation == ExamExecutionOperation.CANCELLING:
            await db.commit()
            return exam
        if control.operation is not None:
            raise ExamStateError(
                "Examination already has a terminal operation in progress"
            )
        if exam.status not in {
            ExamStatus.SEALED,
            ExamStatus.ACTIVE,
            ExamStatus.SUSPENDED,
        }:
            raise ExamStateError(
                "Only SEALED, ACTIVE, or SUSPENDED examinations can be cancelled"
            )

        now = datetime.now(UTC)
        control.operation = ExamExecutionOperation.CANCELLING
        control.operation_source = ExamOperationSource.ADMIN
        control.operation_requested_at = now
        control.operation_requested_by_actor_id = actor.id
        control.operation_reason = normalized_reason
        control.operation_error = None
        exam.status = ExamStatus.CANCELLING

        await ExamExecutionRepository.save_control(db, control)
        await ExamRepository.save_exam(db, exam)
        await cls._add_event(
            db,
            exam_id=exam.id,
            event_type="exam.cancelling",
            payload={"reason": normalized_reason},
        )
        await db.commit()
        return exam

    @staticmethod
    async def _revoke_candidate_sessions(
        db: AsyncSession,
        *,
        candidate_id: UUID,
        at: datetime,
        reason: str,
    ) -> None:
        sessions = await StudentAuthRepository.list_unrevoked_sessions_for_candidate(
            db,
            candidate_id,
            lock=True,
        )
        for session in sessions:
            session.revoked_at = at
            session.revocation_reason = reason
        await StudentAuthRepository.save_sessions(db, sessions)

    @classmethod
    async def _prepare_operation_attempt(cls, db: AsyncSession, exam_id: UUID) -> None:
        control = await ExamExecutionRepository.get_control(db, exam_id, lock=True)
        if control is None or control.operation is None:
            await db.rollback()
            return
        control.operation_attempts += 1
        control.last_operation_attempt_at = datetime.now(UTC)
        control.operation_error = None
        await ExamExecutionRepository.save_control(db, control)
        await db.commit()

    @classmethod
    async def mark_operation_error(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
        message: str,
    ) -> None:
        control = await ExamExecutionRepository.get_control(db, exam_id, lock=True)
        if control is None or control.operation is None:
            await db.rollback()
            return
        control.operation_error = message[:EXECUTION_ERROR_MAX_LENGTH]
        await ExamExecutionRepository.save_control(db, control)
        await db.commit()

    @classmethod
    async def finalize_close(cls, db: AsyncSession, *, exam_id: UUID) -> Exam | None:
        """Finalize every started normal attempt at one deterministic cutoff."""

        await cls._prepare_operation_attempt(db, exam_id)

        while True:
            exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
            if exam is None:
                raise ExamNotFound("Examination does not exist")
            control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
            if (
                control is None
                or control.operation != ExamExecutionOperation.CLOSING
                or control.operation_requested_at is None
            ):
                await db.rollback()
                return exam
            if exam.status != ExamStatus.CLOSING:
                raise ExamStateError("Examination is not in CLOSING state")

            cutoff = control.operation_requested_at
            attempts = await AttemptRepository.list_attempts(
                db,
                exam_id=exam.id,
                statuses=[AttemptStatus.IN_PROGRESS, AttemptStatus.INTERRUPTED],
                limit=FINALIZATION_BATCH_SIZE,
                lock=True,
                skip_locked=False,
            )
            if not attempts:
                await db.rollback()
                break

            for attempt in attempts:
                candidate = await CandidateRepository.get_candidate_by_id(
                    db, attempt.candidate_id, lock=True
                )
                if candidate is None:
                    raise ExamStateError(
                        "Examination attempt candidate no longer exists"
                    )

                if attempt.status == AttemptStatus.IN_PROGRESS:
                    await AttemptService._checkpoint_active_segment(
                        db,
                        attempt=attempt,
                        exam_id=exam.id,
                        at=cutoff,
                    )
                else:
                    interruption = (
                        await AttemptRepository.get_open_interruption_for_attempt(
                            db, attempt.id, lock=True
                        )
                    )
                    if interruption is not None:
                        actor_id = control.operation_requested_by_actor_id
                        if actor_id is None:
                            raise ExamStateError(
                                "Interrupted attempts require administrator closure"
                            )
                        interruption.resumed_at = cutoff
                        interruption.resumed_by_actor_id = actor_id
                        interruption.resume_reason = "Examination closed"
                        await AttemptRepository.save_interruption(db, interruption)

                attempt.status = AttemptStatus.SUBMITTED
                attempt.ended_at = cutoff
                attempt.end_reason = AttemptEndReason.EXAM_CLOSED
                attempt.termination_reason = None
                attempt.active_since = None
                await AttemptRepository.save_attempt(db, attempt)
                await ResultService.calculate_for_submitted_attempt(
                    db,
                    attempt=attempt,
                    candidate=candidate,
                    exam=exam,
                )
                await cls._revoke_candidate_sessions(
                    db,
                    candidate_id=candidate.id,
                    at=cutoff,
                    reason="Examination closed",
                )

            await db.commit()

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
        if (
            control is None
            or control.operation != ExamExecutionOperation.CLOSING
            or control.operation_requested_at is None
        ):
            await db.rollback()
            return exam

        cutoff = control.operation_requested_at
        open_suspension = await ExamRepository.get_open_suspension_for_exam(
            db, exam.id, lock=True
        )
        if open_suspension is not None:
            actor_id = control.operation_requested_by_actor_id
            if actor_id is None:
                raise ExamStateError(
                    "Automatically closing an already-suspended examination is not allowed"
                )
            open_suspension.resumed_at = cutoff
            open_suspension.resumed_by_actor_id = actor_id
            open_suspension.resume_reason = "Closed while suspended"
            await ExamRepository.save_suspension(db, open_suspension)

        exam.status = ExamStatus.CLOSED
        exam.closed_by_actor_id = control.operation_requested_by_actor_id
        exam.closed_at = cutoff
        control.operation = None
        control.result_disposition = ExamResultDisposition.PENDING_REVIEW
        control.results_decided_at = None
        control.results_decided_by_actor_id = None
        control.results_decision_reason = None
        control.operation_error = None

        await ExamRepository.save_exam(db, exam)
        await ExamExecutionRepository.save_control(db, control)
        await cls._add_event(db, exam_id=exam.id, event_type="exam.closed")
        await db.commit()
        return exam

    @classmethod
    async def finalize_cancellation(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
    ) -> Exam | None:
        """Terminate unfinished attempts and permanently void the sitting."""

        await cls._prepare_operation_attempt(db, exam_id)

        while True:
            exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
            if exam is None:
                raise ExamNotFound("Examination does not exist")
            control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
            if (
                control is None
                or control.operation != ExamExecutionOperation.CANCELLING
                or control.operation_requested_at is None
                or control.operation_requested_by_actor_id is None
                or not control.operation_reason
            ):
                await db.rollback()
                return exam
            if exam.status != ExamStatus.CANCELLING:
                raise ExamStateError("Examination is not in CANCELLING state")

            cutoff = control.operation_requested_at
            attempts = await AttemptRepository.list_attempts(
                db,
                exam_id=exam.id,
                statuses=[AttemptStatus.IN_PROGRESS, AttemptStatus.INTERRUPTED],
                limit=FINALIZATION_BATCH_SIZE,
                lock=True,
                skip_locked=False,
            )
            if not attempts:
                await db.rollback()
                break

            for attempt in attempts:
                if attempt.status == AttemptStatus.IN_PROGRESS:
                    await AttemptService._checkpoint_active_segment(
                        db,
                        attempt=attempt,
                        exam_id=exam.id,
                        at=cutoff,
                    )
                else:
                    interruption = (
                        await AttemptRepository.get_open_interruption_for_attempt(
                            db, attempt.id, lock=True
                        )
                    )
                    if interruption is not None:
                        interruption.resumed_at = cutoff
                        interruption.resumed_by_actor_id = (
                            control.operation_requested_by_actor_id
                        )
                        interruption.resume_reason = "Examination cancelled"
                        await AttemptRepository.save_interruption(db, interruption)

                attempt.status = AttemptStatus.TERMINATED
                attempt.ended_at = cutoff
                attempt.end_reason = AttemptEndReason.EXAM_CANCELLED
                attempt.termination_reason = control.operation_reason
                attempt.active_since = None
                await AttemptRepository.save_attempt(db, attempt)
                await cls._revoke_candidate_sessions(
                    db,
                    candidate_id=attempt.candidate_id,
                    at=cutoff,
                    reason="Examination cancelled",
                )

            await db.commit()

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
        if (
            control is None
            or control.operation != ExamExecutionOperation.CANCELLING
            or control.operation_requested_at is None
            or control.operation_requested_by_actor_id is None
            or not control.operation_reason
        ):
            await db.rollback()
            return exam

        cutoff = control.operation_requested_at
        actor_id = control.operation_requested_by_actor_id
        open_suspension = await ExamRepository.get_open_suspension_for_exam(
            db, exam.id, lock=True
        )
        if open_suspension is not None:
            open_suspension.resumed_at = cutoff
            open_suspension.resumed_by_actor_id = actor_id
            open_suspension.resume_reason = "Cancelled while suspended"
            await ExamRepository.save_suspension(db, open_suspension)

        exam.status = ExamStatus.CANCELLED
        exam.cancelled_by_actor_id = actor_id
        exam.cancelled_at = cutoff
        exam.cancellation_reason = control.operation_reason
        control.operation = None
        control.result_disposition = ExamResultDisposition.VOIDED
        control.results_decided_at = cutoff
        control.results_decided_by_actor_id = actor_id
        control.results_decision_reason = control.operation_reason
        control.operation_error = None

        await ExamRepository.save_exam(db, exam)
        await ExamExecutionRepository.save_control(db, control)
        await cls._add_event(
            db,
            exam_id=exam.id,
            event_type="exam.cancelled",
            payload={"reason": exam.cancellation_reason},
        )
        await db.commit()
        return exam

    @classmethod
    async def approve_results(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> ExamExecutionControl:
        cls._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.CLOSED:
            raise ExamStateError(
                "Results can only be approved for a CLOSED examination"
            )

        control = await ExamExecutionRepository.get_or_create_control(
            db, exam.id, lock=True
        )
        if control.operation is not None:
            raise ExamStateError("Examination finalization is still in progress")
        if control.result_disposition is None:
            control.result_disposition = ExamResultDisposition.PENDING_REVIEW
        if control.result_disposition != ExamResultDisposition.PENDING_REVIEW:
            raise ExamStateError("Examination results are no longer pending review")

        now = datetime.now(UTC)
        control.result_disposition = ExamResultDisposition.APPROVED
        control.results_decided_at = now
        control.results_decided_by_actor_id = actor.id
        control.results_decision_reason = None
        await ExamExecutionRepository.save_control(db, control)
        await cls._add_event(db, exam_id=exam.id, event_type="exam.results_approved")
        await db.commit()
        return control

    @classmethod
    async def void_results(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        reason: str,
    ) -> ExamExecutionControl:
        cls._require_admin(actor)
        normalized_reason = cls._require_reason(reason)
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.CLOSED:
            raise ExamStateError("Results can only be voided for a CLOSED examination")

        control = await ExamExecutionRepository.get_or_create_control(
            db, exam.id, lock=True
        )
        if control.operation is not None:
            raise ExamStateError("Examination finalization is still in progress")
        if control.result_disposition is None:
            control.result_disposition = ExamResultDisposition.PENDING_REVIEW
        if control.result_disposition != ExamResultDisposition.PENDING_REVIEW:
            raise ExamStateError("Examination results are no longer pending review")

        sync_activity = await db.scalar(
            select(
                exists().where(
                    ExamResult.exam_id == exam.id,
                    or_(
                        ExamResult.sync_status != ResultSyncStatus.PENDING,
                        ExamResult.sync_batch_id.is_not(None),
                    ),
                )
            )
        )
        if sync_activity:
            raise ExamStateError(
                "Results cannot be voided after external synchronization has started"
            )

        now = datetime.now(UTC)
        control.result_disposition = ExamResultDisposition.VOIDED
        control.results_decided_at = now
        control.results_decided_by_actor_id = actor.id
        control.results_decision_reason = normalized_reason
        await ExamExecutionRepository.save_control(db, control)
        await cls._add_event(
            db,
            exam_id=exam.id,
            event_type="exam.results_voided",
            payload={"reason": normalized_reason},
        )
        await db.commit()
        return control

    @staticmethod
    async def results_are_approved(db: AsyncSession, *, exam_id: UUID) -> bool:
        control = await ExamExecutionRepository.get_control(db, exam_id)
        return bool(
            control is not None
            and control.result_disposition == ExamResultDisposition.APPROVED
        )

    @staticmethod
    async def results_are_voided(db: AsyncSession, *, exam_id: UUID) -> bool:
        control = await ExamExecutionRepository.get_control(db, exam_id)
        return bool(
            control is not None
            and control.result_disposition == ExamResultDisposition.VOIDED
        )

    @staticmethod
    async def get_control(
        db: AsyncSession,
        *,
        exam_id: UUID,
    ) -> ExamExecutionControl | None:
        return await ExamExecutionRepository.get_control(db, exam_id)

    @classmethod
    async def evaluate_automatic_close(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
        at: datetime | None = None,
    ) -> bool:
        """Request automatic closure only when nobody can legitimately continue/start."""

        now = at or datetime.now(UTC)
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None or exam.status != ExamStatus.ACTIVE:
            await db.rollback()
            return False

        control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
        if control is not None and control.operation is not None:
            await db.rollback()
            return False

        unfinished = await db.scalar(
            select(
                exists()
                .where(ExamCandidate.exam_id == exam.id)
                .where(ExamAttempt.candidate_id == ExamCandidate.id)
                .where(
                    ExamAttempt.status.in_(
                        [AttemptStatus.IN_PROGRESS, AttemptStatus.INTERRUPTED]
                    )
                )
            )
        )
        if unfinished:
            await db.rollback()
            return False

        unstarted_candidate_exists = await db.scalar(
            select(
                exists().where(
                    ExamCandidate.exam_id == exam.id,
                    ExamCandidate.status == CandidateStatus.ELIGIBLE,
                    ~exists().where(ExamAttempt.candidate_id == ExamCandidate.id),
                )
            )
        )
        if not unstarted_candidate_exists:
            # Keep the exam lock until the close request commits. Rollback would
            # both expire ORM fields and allow a new starter between these steps.
            await cls.request_automatic_close(db, exam_id=exam_id, requested_at=now)
            return True

        deadline = await AttemptService._effective_late_start_deadline(exam)
        if deadline is None or now <= deadline:
            await db.rollback()
            return False

        usable_late_start_exists = await db.scalar(
            select(
                exists().where(
                    ExamCandidate.exam_id == exam.id,
                    ExamCandidate.status == CandidateStatus.ELIGIBLE,
                    ~exists().where(ExamAttempt.candidate_id == ExamCandidate.id),
                    CandidateLateStartAuthorization.candidate_id == ExamCandidate.id,
                    CandidateLateStartAuthorization.consumed_at.is_(None),
                    CandidateLateStartAuthorization.revoked_at.is_(None),
                    or_(
                        CandidateLateStartAuthorization.expires_at.is_(None),
                        CandidateLateStartAuthorization.expires_at >= now,
                    ),
                )
            )
        )
        if usable_late_start_exists:
            await db.rollback()
            return False

        await cls.request_automatic_close(db, exam_id=exam_id, requested_at=now)
        return True

    @classmethod
    async def suspend_active_exams_after_runtime_gap(
        cls,
        db: AsyncSession,
        *,
        outage_started_at: datetime,
        reason: str,
    ) -> list[UUID]:
        """Conservatively pause active exams after an unclean runtime gap.

        The suspension is backdated to the last durable healthy heartbeat (but
        never before activation) so candidates do not lose outage time.
        """

        now = datetime.now(UTC)
        query = (
            select(Exam)
            .where(Exam.status == ExamStatus.ACTIVE)
            .order_by(Exam.id.asc())
            .with_for_update(of=Exam)
        )
        exams = list((await db.execute(query)).scalars().all())
        if not exams:
            await db.rollback()
            return []

        suspended_ids: list[UUID] = []
        for exam in exams:
            cutoff = outage_started_at
            if exam.activated_at is not None and cutoff < exam.activated_at:
                cutoff = exam.activated_at
            cutoff = min(cutoff, now)

            open_suspension = await ExamRepository.get_open_suspension_for_exam(
                db, exam.id, lock=True
            )
            if open_suspension is None:
                await ExamRepository.add_suspension(
                    db,
                    ExamSuspension(
                        exam_id=exam.id,
                        source=ExamSuspensionSource.SYSTEM,
                        suspended_at=cutoff,
                        suspended_by_actor_id=None,
                        reason=reason,
                    ),
                )
            exam.status = ExamStatus.SUSPENDED
            await ExamRepository.save_exam(db, exam)
            await cls._add_event(
                db,
                exam_id=exam.id,
                event_type="exam.suspended",
                payload={"reason": reason, "source": "system"},
            )
            suspended_ids.append(exam.id)

        await db.commit()
        return suspended_ids

    @staticmethod
    async def list_pending_operation_exam_ids(
        db: AsyncSession,
    ) -> tuple[list[UUID], list[UUID]]:
        closing = list(
            (
                await db.execute(
                    select(Exam.id)
                    .where(Exam.status == ExamStatus.CLOSING)
                    .order_by(Exam.id.asc())
                )
            )
            .scalars()
            .all()
        )
        cancelling = list(
            (
                await db.execute(
                    select(Exam.id)
                    .where(Exam.status == ExamStatus.CANCELLING)
                    .order_by(Exam.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return closing, cancelling
