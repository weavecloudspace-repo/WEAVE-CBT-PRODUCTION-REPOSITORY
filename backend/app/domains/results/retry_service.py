"""Operator-controlled recovery for definitive result synchronization failures."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError
from app.domains.auth.models import LocalActor
from app.domains.exams.exceptions import ExamNotFound, ExamStateError
from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.models import ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.results.models import ExamResult, ResultSyncStatus
from app.domains.results.repository import ResultRepository


class ResultRetryService:
    """Reset only detached FAILED rows after an operator fixes the root cause.

    FAILED rows that still carry ``sync_batch_id`` represent uncertain delivery
    and must keep replaying the exact same idempotency batch; maintenance owns
    those retries. Rows with a null batch ID are definitive rejects and require
    this deliberate reset before a fresh batch can be created.
    """

    @staticmethod
    def _require_admin(actor: LocalActor) -> None:
        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")
        if actor.role != "admin":
            raise AcademicAuthorizationError("Administrator access is required")

    @classmethod
    async def retry_detached_failures(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> int:
        cls._require_admin(actor)

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.CLOSED:
            raise ExamStateError(
                "Result synchronization can only be retried for a CLOSED examination"
            )

        control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
        if (
            control is None
            or control.result_disposition != ExamResultDisposition.APPROVED
        ):
            raise ExamStateError(
                "Examination results must remain APPROVED before synchronization can be retried"
            )

        rows = list(
            (
                await db.execute(
                    select(ExamResult)
                    .where(
                        ExamResult.exam_id == exam.id,
                        ExamResult.sync_status == ResultSyncStatus.FAILED,
                        ExamResult.voided_at.is_(None),
                        ExamResult.sync_batch_id.is_(None),
                    )
                    .order_by(ExamResult.calculated_at.asc(), ExamResult.id.asc())
                    .with_for_update(of=ExamResult)
                )
            )
            .scalars()
            .all()
        )

        for row in rows:
            row.sync_status = ResultSyncStatus.PENDING
            row.sync_batch_id = None
            row.synced_at = None
            row.sync_error = None
            # Preserve sync_attempts and last_sync_attempt_at as audit history.

        await ResultRepository.save_results(db, rows)
        await db.commit()
        return len(rows)
