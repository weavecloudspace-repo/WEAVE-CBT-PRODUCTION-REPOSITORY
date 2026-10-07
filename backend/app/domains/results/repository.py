"""Persistence operations for locally calculated examination results.

The repository reads and writes result models but does not calculate scores,
decide synchronization transitions, call Weave, or commit transactions. Those
responsibilities belong to result/synchronization services and workers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.results.models import ExamResult, ResultSyncStatus


class ResultRepository:
    """Provide database operations for locally calculated exam results."""

    @staticmethod
    async def add_result(
        db: AsyncSession,
        exam_result: ExamResult,
    ) -> ExamResult:
        db.add(exam_result)
        await db.flush()
        return exam_result

    @staticmethod
    async def add_results(
        db: AsyncSession,
        exam_results: Sequence[ExamResult],
    ) -> list[ExamResult]:
        rows = list(exam_results)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def save_result(
        db: AsyncSession,
        exam_result: ExamResult,
    ) -> ExamResult:
        db.add(exam_result)
        await db.flush()
        return exam_result

    @staticmethod
    async def save_results(
        db: AsyncSession,
        exam_results: Sequence[ExamResult],
    ) -> list[ExamResult]:
        rows = list(exam_results)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_result_by_id(
        db: AsyncSession,
        result_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamResult | None:
        query = select(ExamResult).where(ExamResult.id == result_id)
        if lock:
            query = query.with_for_update(of=ExamResult).execution_options(
                populate_existing=True
            )
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_result_by_attempt_id(
        db: AsyncSession,
        attempt_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamResult | None:
        query = select(ExamResult).where(ExamResult.attempt_id == attempt_id)
        if lock:
            query = query.with_for_update(of=ExamResult)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_result_for_candidate_exam(
        db: AsyncSession,
        candidate_id: UUID,
        exam_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamResult | None:
        query = select(ExamResult).where(
            ExamResult.candidate_id == candidate_id,
            ExamResult.exam_id == exam_id,
        )
        if lock:
            query = query.with_for_update(of=ExamResult)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_retryable_sync_batch_id_for_exam(
        db: AsyncSession,
        *,
        exam_id: UUID,
    ) -> UUID | None:
        """Return the oldest FAILED batch whose identity must be preserved."""

        query = (
            select(ExamResult)
            .where(
                ExamResult.exam_id == exam_id,
                ExamResult.sync_status == ResultSyncStatus.FAILED,
                ExamResult.voided_at.is_(None),
                ExamResult.sync_batch_id.is_not(None),
            )
            .order_by(
                ExamResult.last_sync_attempt_at.asc().nullsfirst(),
                ExamResult.calculated_at.asc(),
                ExamResult.id.asc(),
            )
            .limit(1)
        )
        row = (await db.execute(query)).scalar_one_or_none()
        return row.sync_batch_id if row is not None else None

    @staticmethod
    async def list_pending_results_for_exam_sync(
        db: AsyncSession,
        *,
        exam_id: UUID,
        limit: int,
        lock: bool = False,
    ) -> list[ExamResult]:
        """Return fresh PENDING results not yet assigned to a durable batch."""

        query = (
            select(ExamResult)
            .where(
                ExamResult.exam_id == exam_id,
                ExamResult.sync_status == ResultSyncStatus.PENDING,
                ExamResult.voided_at.is_(None),
                ExamResult.sync_batch_id.is_(None),
            )
            .order_by(
                ExamResult.calculated_at.asc(),
                ExamResult.candidate_id.asc(),
                ExamResult.id.asc(),
            )
            .limit(limit)
        )
        if lock:
            query = query.with_for_update(of=ExamResult)
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_results_for_sync_batch(
        db: AsyncSession,
        sync_batch_id: UUID,
        *,
        lock: bool = False,
    ) -> list[ExamResult]:
        """Return the exact durable membership of one Weave result batch."""

        query = (
            select(ExamResult)
            .where(ExamResult.sync_batch_id == sync_batch_id)
            .order_by(
                ExamResult.calculated_at.asc(),
                ExamResult.candidate_id.asc(),
                ExamResult.id.asc(),
            )
        )
        if lock:
            query = query.with_for_update(of=ExamResult)
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_results_for_exam(
        db: AsyncSession,
        exam_id: UUID,
        *,
        sync_statuses: Sequence[ResultSyncStatus] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[ExamResult]:
        query = select(ExamResult).where(ExamResult.exam_id == exam_id)
        if sync_statuses is not None:
            statuses = list(sync_statuses)
            if not statuses:
                return []
            query = query.where(ExamResult.sync_status.in_(statuses))
        query = query.order_by(
            ExamResult.calculated_at.asc(),
            ExamResult.candidate_id.asc(),
            ExamResult.id.asc(),
        ).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def count_results_for_exam(
        db: AsyncSession,
        exam_id: UUID,
        *,
        sync_status: ResultSyncStatus | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ExamResult)
            .where(ExamResult.exam_id == exam_id)
        )
        if sync_status is not None:
            query = query.where(ExamResult.sync_status == sync_status)
        return int((await db.execute(query)).scalar_one() or 0)

    @staticmethod
    async def list_results_for_candidate(
        db: AsyncSession,
        candidate_id: UUID,
    ) -> list[ExamResult]:
        result = await db.execute(
            select(ExamResult)
            .where(ExamResult.candidate_id == candidate_id)
            .order_by(
                ExamResult.calculated_at.desc(),
                ExamResult.id.desc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_results_for_component(
        db: AsyncSession,
        assessment_component_id: UUID,
        *,
        sync_statuses: Sequence[ResultSyncStatus] | None = None,
    ) -> list[ExamResult]:
        query = select(ExamResult).where(
            ExamResult.assessment_component_id == assessment_component_id
        )
        if sync_statuses is not None:
            statuses = list(sync_statuses)
            if not statuses:
                return []
            query = query.where(ExamResult.sync_status.in_(statuses))
        result = await db.execute(
            query.order_by(
                ExamResult.calculated_at.asc(),
                ExamResult.candidate_id.asc(),
                ExamResult.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_results_for_sync(
        db: AsyncSession,
        sync_statuses: Sequence[ResultSyncStatus],
        *,
        retry_before: datetime | None = None,
        limit: int | None = None,
        lock: bool = False,
        skip_locked: bool = False,
    ) -> list[ExamResult]:
        """Return deterministic sync work, optionally claiming rows with locks."""

        statuses = list(sync_statuses)
        if not statuses:
            return []

        query = select(ExamResult).where(
            ExamResult.sync_status.in_(statuses), ExamResult.voided_at.is_(None)
        )
        if retry_before is not None:
            query = query.where(
                (ExamResult.last_sync_attempt_at.is_(None))
                | (ExamResult.last_sync_attempt_at <= retry_before)
            )
        query = query.order_by(
            ExamResult.last_sync_attempt_at.asc().nullsfirst(),
            ExamResult.calculated_at.asc(),
            ExamResult.id.asc(),
        )
        if limit is not None:
            query = query.limit(limit)
        if lock:
            query = query.with_for_update(
                of=ExamResult,
                skip_locked=skip_locked,
            )
        return list((await db.execute(query)).scalars().all())
