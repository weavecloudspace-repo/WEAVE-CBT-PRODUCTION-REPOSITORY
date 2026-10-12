"""Read-oriented persistence helpers for attempt monitoring."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.attempts.models import AttemptStatus, ExamAttempt
from app.domains.candidates.models import ExamCandidate


class AttemptQueryRepository:
    """Provide paginated attempt-monitoring reads without lifecycle mutation."""

    @staticmethod
    def _apply_filters(
        query,
        *,
        exam_id: UUID,
        statuses: Sequence[AttemptStatus] | None,
        candidate_id: UUID | None,
    ):
        query = query.join(
            ExamCandidate,
            ExamCandidate.id == ExamAttempt.candidate_id,
        ).where(ExamCandidate.exam_id == exam_id)

        if candidate_id is not None:
            query = query.where(ExamAttempt.candidate_id == candidate_id)

        if statuses is not None:
            values = list(statuses)
            if not values:
                return query.where(False)
            query = query.where(ExamAttempt.status.in_(values))

        return query

    @classmethod
    async def list_exam_attempts(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
        statuses: Sequence[AttemptStatus] | None = None,
        candidate_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ExamAttempt]:
        query = cls._apply_filters(
            select(ExamAttempt),
            exam_id=exam_id,
            statuses=statuses,
            candidate_id=candidate_id,
        )
        result = await db.execute(
            query.order_by(
                ExamAttempt.started_at.asc(),
                ExamAttempt.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def count_exam_attempts(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
        statuses: Sequence[AttemptStatus] | None = None,
        candidate_id: UUID | None = None,
    ) -> int:
        query = cls._apply_filters(
            select(func.count(func.distinct(ExamAttempt.id))).select_from(ExamAttempt),
            exam_id=exam_id,
            statuses=statuses,
            candidate_id=candidate_id,
        )
        return int((await db.execute(query)).scalar_one() or 0)
