"""Recovery sweeps for durable CBT background work.

PostgreSQL is the source of truth. Redis/ARQ is only job delivery, so every
important background workflow can be reconstructed after Redis loss, worker
termination, API restart, or a failed enqueue.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from arq.connections import ArqRedis
from sqlalchemy import and_, or_, select

from app.core.database import async_session_factory
from app.domains.exams.execution_models import (
    ExamExecutionControl,
    ExamResultDisposition,
)
from app.domains.exams.lineage import latest_exam_revision_clause
from app.domains.exams.models import Exam, ExamRosterStatus, ExamStatus
from app.domains.results.models import (
    RESULT_SYNC_ERROR_MAX_LENGTH,
    ExamResult,
    ResultSyncStatus,
)

logger = logging.getLogger(__name__)

MAINTENANCE_SCAN_LIMIT = 500
RESULT_FAILED_RETRY_AFTER = timedelta(minutes=5)
RESULT_SYNCING_STALE_AFTER = timedelta(minutes=10)

_STALE_RESULT_ERROR = (
    "Previous result synchronization worker stopped before completion; "
    "the durable batch has been scheduled for recovery."
)


def _arq_redis_from_context(ctx: dict[str, Any]) -> ArqRedis:
    redis = ctx.get("redis")
    if redis is None:
        raise RuntimeError("ARQ maintenance context is missing the Redis connection")
    return cast(ArqRedis, redis)


async def _recover_stale_result_batches(*, now: datetime) -> set[UUID]:
    """Recover complete durable batches instead of splitting them by row limit."""

    stale_before = now - RESULT_SYNCING_STALE_AFTER
    error_message = _STALE_RESULT_ERROR[:RESULT_SYNC_ERROR_MAX_LENGTH]
    recovered_exam_ids: set[UUID] = set()

    async with async_session_factory() as db:
        batch_rows = list(
            (
                await db.execute(
                    select(ExamResult.sync_batch_id, ExamResult.exam_id)
                    .where(
                        ExamResult.sync_status == ResultSyncStatus.SYNCING,
                        ExamResult.sync_batch_id.is_not(None),
                        ExamResult.last_sync_attempt_at.is_not(None),
                        ExamResult.last_sync_attempt_at <= stale_before,
                    )
                    .distinct()
                    .order_by(ExamResult.sync_batch_id.asc())
                    .limit(MAINTENANCE_SCAN_LIMIT)
                )
            )
            .tuples()
            .all()
        )
        await db.rollback()

    for batch_id, exam_id in batch_rows:
        if batch_id is None:
            continue
        async with async_session_factory() as db:
            rows = list(
                (
                    await db.execute(
                        select(ExamResult)
                        .where(ExamResult.sync_batch_id == batch_id)
                        .order_by(ExamResult.id.asc())
                        .with_for_update(of=ExamResult)
                    )
                )
                .scalars()
                .all()
            )
            changed = 0
            for row in rows:
                if row.sync_status != ResultSyncStatus.SYNCING:
                    continue
                if (
                    row.last_sync_attempt_at is None
                    or row.last_sync_attempt_at > stale_before
                ):
                    continue
                row.sync_status = ResultSyncStatus.FAILED
                row.synced_at = None
                row.sync_error = error_message
                changed += 1
            if changed:
                await db.commit()
                recovered_exam_ids.add(exam_id)
            else:
                await db.rollback()

    if recovered_exam_ids:
        logger.warning(
            "Recovered stale result synchronization batches across %s exam(s)",
            len(recovered_exam_ids),
        )
    return recovered_exam_ids


async def _list_roster_exam_ids_needing_recovery() -> tuple[list[UUID], list[UUID]]:
    """Return durable preparation and reconciliation work for current rosters."""

    async with async_session_factory() as db:
        pending = list(
            (
                await db.execute(
                    select(Exam.id)
                    .where(
                        Exam.status == ExamStatus.SEALED,
                        Exam.roster_status == ExamRosterStatus.PENDING,
                        latest_exam_revision_clause(),
                    )
                    .order_by(Exam.updated_at.asc(), Exam.id.asc())
                    .limit(MAINTENANCE_SCAN_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        stale = list(
            (
                await db.execute(
                    select(Exam.id)
                    .where(
                        Exam.status == ExamStatus.SEALED,
                        Exam.roster_status == ExamRosterStatus.STALE,
                        latest_exam_revision_clause(),
                    )
                    .order_by(Exam.updated_at.asc(), Exam.id.asc())
                    .limit(MAINTENANCE_SCAN_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        await db.rollback()
        return pending, stale


async def _list_exam_execution_recovery_ids() -> tuple[
    list[UUID], list[UUID], list[UUID]
]:
    async with async_session_factory() as db:
        closing = list(
            (
                await db.execute(
                    select(Exam.id)
                    .where(Exam.status == ExamStatus.CLOSING)
                    .order_by(Exam.updated_at.asc(), Exam.id.asc())
                    .limit(MAINTENANCE_SCAN_LIMIT)
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
                    .order_by(Exam.updated_at.asc(), Exam.id.asc())
                    .limit(MAINTENANCE_SCAN_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        active = list(
            (
                await db.execute(
                    select(Exam.id)
                    .where(Exam.status == ExamStatus.ACTIVE)
                    .order_by(Exam.updated_at.asc(), Exam.id.asc())
                    .limit(MAINTENANCE_SCAN_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return closing, cancelling, active


async def _list_result_exam_ids_needing_recovery(*, now: datetime) -> list[UUID]:
    """Only explicitly APPROVED closed exams are eligible for Weave sync."""

    failed_before = now - RESULT_FAILED_RETRY_AFTER
    async with async_session_factory() as db:
        query = (
            select(ExamResult.exam_id)
            .join(Exam, Exam.id == ExamResult.exam_id)
            .join(
                ExamExecutionControl,
                ExamExecutionControl.exam_id == Exam.id,
            )
            .where(
                Exam.status == ExamStatus.CLOSED,
                ExamResult.voided_at.is_(None),
                ExamExecutionControl.result_disposition
                == ExamResultDisposition.APPROVED,
                or_(
                    and_(
                        ExamResult.sync_status == ResultSyncStatus.PENDING,
                        ExamResult.sync_batch_id.is_(None),
                    ),
                    and_(
                        ExamResult.sync_status == ResultSyncStatus.FAILED,
                        ExamResult.sync_batch_id.is_not(None),
                        or_(
                            ExamResult.last_sync_attempt_at.is_(None),
                            ExamResult.last_sync_attempt_at <= failed_before,
                        ),
                    ),
                ),
            )
            .distinct()
            .order_by(ExamResult.exam_id.asc())
            .limit(MAINTENANCE_SCAN_LIMIT)
        )
        return list((await db.execute(query)).scalars().all())


async def _filter_approved_exam_ids(exam_ids: set[UUID]) -> set[UUID]:
    if not exam_ids:
        return set()
    async with async_session_factory() as db:
        rows = await db.execute(
            select(ExamExecutionControl.exam_id).where(
                ExamExecutionControl.exam_id.in_(exam_ids),
                ExamExecutionControl.result_disposition
                == ExamResultDisposition.APPROVED,
            )
        )
        return set(rows.scalars().all())


async def recover_background_work(ctx: dict[str, Any]) -> dict[str, int]:
    """Reconstruct all durable background work from PostgreSQL state."""

    redis = _arq_redis_from_context(ctx)
    now = datetime.now(UTC)

    stale_result_exam_ids = await _recover_stale_result_batches(now=now)
    (
        pending_roster_ids,
        stale_roster_ids,
    ) = await _list_roster_exam_ids_needing_recovery()
    closing_ids, cancelling_ids, active_ids = await _list_exam_execution_recovery_ids()
    result_exam_ids = set(await _list_result_exam_ids_needing_recovery(now=now))
    result_exam_ids.update(await _filter_approved_exam_ids(stale_result_exam_ids))

    # One global sweep covers normal and makeup attempts. The stable job ID
    # prevents overlapping timeout scans when one maintenance pass runs long.
    timeout_job = await redis.enqueue_job(
        "finalize_expired_attempts",
        _job_id="exam-timeout-sweep",
    )

    for exam_id in pending_roster_ids:
        await redis.enqueue_job("prepare_exam_roster", str(exam_id))
    for exam_id in stale_roster_ids:
        await redis.enqueue_job("reconcile_exam_roster", str(exam_id))
    for exam_id in closing_ids:
        await redis.enqueue_job("finalize_exam_close", str(exam_id))
    for exam_id in cancelling_ids:
        await redis.enqueue_job("finalize_exam_cancellation", str(exam_id))
    for exam_id in active_ids:
        await redis.enqueue_job("evaluate_exam_completion", str(exam_id))
    for exam_id in sorted(result_exam_ids, key=str):
        await redis.enqueue_job("sync_exam_results", str(exam_id))

    timeout_jobs_enqueued = 1 if timeout_job is not None else 0
    total = (
        len(pending_roster_ids)
        + len(stale_roster_ids)
        + len(closing_ids)
        + len(cancelling_ids)
        + len(active_ids)
        + len(result_exam_ids)
        + timeout_jobs_enqueued
    )
    if total:
        logger.info(
            "Maintenance enqueued timeout=%s roster_prepare=%s roster_reconcile=%s "
            "closing=%s cancelling=%s completion=%s results=%s",
            timeout_jobs_enqueued,
            len(pending_roster_ids),
            len(stale_roster_ids),
            len(closing_ids),
            len(cancelling_ids),
            len(active_ids),
            len(result_exam_ids),
        )

    return {
        "timeout_jobs_enqueued": timeout_jobs_enqueued,
        "roster_jobs_enqueued": len(pending_roster_ids),
        "roster_reconcile_jobs_enqueued": len(stale_roster_ids),
        "closing_jobs_enqueued": len(closing_ids),
        "cancelling_jobs_enqueued": len(cancelling_ids),
        "completion_jobs_enqueued": len(active_ids),
        "result_jobs_enqueued": len(result_exam_ids),
        "stale_result_exams_recovered": len(stale_result_exam_ids),
    }
