"""Read-oriented services for live examination attempt monitoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.attempts.models import AttemptStatus, ExamAttempt
from app.domains.attempts.query_repository import AttemptQueryRepository
from app.domains.attempts.query_schemas import (
    AttemptConnectivityStatus,
    AttemptMonitorResponse,
)
from app.domains.attempts.runtime_repository import AttemptRuntimeRepository
from app.domains.attempts.service import AttemptService, AttemptStateError
from app.domains.auth.models import LocalActor
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.exceptions import ExamNotFound
from app.domains.exams.repository import ExamRepository

ATTEMPT_HEARTBEAT_ONLINE_WITHIN = timedelta(seconds=45)
ATTEMPT_HEARTBEAT_STALE_AFTER = timedelta(seconds=120)


class AttemptQueryService:
    """Provide authorized invigilation reads over durable attempt state."""

    @staticmethod
    def _remaining_seconds(
        attempt: ExamAttempt,
        *,
        suspensions: list,
        at: datetime,
    ) -> int:
        consumed = attempt.elapsed_seconds

        if (
            attempt.status == AttemptStatus.IN_PROGRESS
            and attempt.active_since is not None
        ):
            total = max(0, int((at - attempt.active_since).total_seconds()))
            suspended = 0
            for suspension in suspensions:
                end = suspension.resumed_at or at
                overlap_start = max(attempt.active_since, suspension.suspended_at)
                overlap_end = min(at, end)
                if overlap_end > overlap_start:
                    suspended += int((overlap_end - overlap_start).total_seconds())
            consumed += max(0, total - suspended)

        return max(0, attempt.time_limit_seconds - consumed)

    @staticmethod
    def _connectivity(
        attempt: ExamAttempt,
        *,
        at: datetime,
    ) -> tuple[AttemptConnectivityStatus, int]:
        age_seconds = max(0, int((at - attempt.last_heartbeat_at).total_seconds()))
        if attempt.status in {AttemptStatus.SUBMITTED, AttemptStatus.TERMINATED}:
            return AttemptConnectivityStatus.TERMINAL, age_seconds
        if at - attempt.last_heartbeat_at <= ATTEMPT_HEARTBEAT_ONLINE_WITHIN:
            return AttemptConnectivityStatus.ONLINE, age_seconds
        if at - attempt.last_heartbeat_at <= ATTEMPT_HEARTBEAT_STALE_AFTER:
            return AttemptConnectivityStatus.RECENTLY_DISCONNECTED, age_seconds
        return AttemptConnectivityStatus.STALE, age_seconds

    @staticmethod
    async def list_exam_attempts(
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        statuses: list[AttemptStatus] | None = None,
        candidate_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[AttemptMonitorResponse], int]:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        await AttemptService._require_operator(
            db,
            actor=actor,
            exam_id=exam.id,
        )

        attempts = await AttemptQueryRepository.list_exam_attempts(
            db,
            exam_id=exam.id,
            statuses=statuses,
            candidate_id=candidate_id,
            offset=offset,
            limit=limit,
        )
        total = await AttemptQueryRepository.count_exam_attempts(
            db,
            exam_id=exam.id,
            statuses=statuses,
            candidate_id=candidate_id,
        )

        if not attempts:
            return [], total

        candidates = await CandidateRepository.list_candidates_for_exam(
            db,
            exam.id,
            limit=None,
        )
        candidates_by_id = {candidate.id: candidate for candidate in candidates}
        suspensions = await AttemptRuntimeRepository.list_exam_suspensions(db, exam.id)
        now = datetime.now(UTC)

        response: list[AttemptMonitorResponse] = []
        for attempt in attempts:
            candidate = candidates_by_id.get(attempt.candidate_id)
            if candidate is None:
                raise AttemptStateError(
                    "Attempt references an unavailable examination candidate"
                )

            connectivity, heartbeat_age_seconds = AttemptQueryService._connectivity(
                attempt,
                at=now,
            )
            response.append(
                AttemptMonitorResponse(
                    id=attempt.id,
                    candidate_id=candidate.id,
                    admission_number=candidate.admission_number,
                    candidate_name=candidate.display_name,
                    class_id=candidate.class_id,
                    status=attempt.status,
                    started_at=attempt.started_at,
                    ended_at=attempt.ended_at,
                    end_reason=attempt.end_reason,
                    termination_reason=attempt.termination_reason,
                    time_limit_seconds=attempt.time_limit_seconds,
                    remaining_seconds=AttemptQueryService._remaining_seconds(
                        attempt,
                        suspensions=suspensions,
                        at=now,
                    ),
                    last_heartbeat_at=attempt.last_heartbeat_at,
                    heartbeat_age_seconds=heartbeat_age_seconds,
                    connectivity=connectivity,
                    last_activity_at=attempt.last_activity_at,
                )
            )

        return response, total
