"""ARQ jobs for synchronizing approved CBT results to Weave Cloud."""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.database import async_session_factory
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.results.approved_sync_service import approved_result_sync_service
from app.domains.results.models import ResultSyncStatus
from app.domains.results.repository import ResultRepository

logger = logging.getLogger(__name__)


async def sync_exam_results(_ctx: dict, exam_id: str) -> None:
    """Synchronize all currently pending approved result batches for one exam."""

    try:
        parsed_exam_id = UUID(exam_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("sync_exam_results received an invalid exam ID") from exc

    logger.info("Starting result synchronization for exam %s", parsed_exam_id)
    batches_processed = 0
    results_rejected = 0

    try:
        async with async_session_factory() as db:
            # Worker-level guard gives a cheap early exit. The service facade
            # repeats the guard so accidental direct job/service invocation
            # still cannot bypass academic approval.
            approved = await ExamExecutionService.results_are_approved(
                db,
                exam_id=parsed_exam_id,
            )
            await db.rollback()
            if not approved:
                logger.info(
                    "Skipping result synchronization for exam %s because results are not approved",
                    parsed_exam_id,
                )
                return

            while True:
                response = await approved_result_sync_service.sync_next_batch(
                    db,
                    exam_id=parsed_exam_id,
                )
                if response is None:
                    break
                batches_processed += 1
                results_rejected += response.rejected
                if response.rejected:
                    logger.warning(
                        "Weave rejected %s results for exam %s in batch %s: %s. "
                        "Correct the reported issues before using retry-sync.",
                        response.rejected,
                        parsed_exam_id,
                        response.batch_id,
                        "; ".join(f"{error.code}: {error.detail}" for error in response.errors),
                    )
                logger.info(
                    "Synchronized result batch %s for exam %s: received=%s applied=%s unchanged=%s rejected=%s",
                    response.batch_id,
                    parsed_exam_id,
                    response.received,
                    response.applied,
                    response.unchanged,
                    response.rejected,
                )
            failed_rows = await ResultRepository.list_results_for_exam(
                db,
                parsed_exam_id,
                sync_statuses=[ResultSyncStatus.FAILED],
            )
            active_failures = [row for row in failed_rows if row.voided_at is None]
            if active_failures:
                logger.warning(
                    "Result synchronization remains incomplete for exam %s: "
                    "%s failed results. Reasons: %s",
                    parsed_exam_id,
                    len(active_failures),
                    "; ".join(sorted({row.sync_error or "No failure reason recorded" for row in active_failures})),
                )
            await db.rollback()
    except Exception:
        logger.exception(
            "Result synchronization job failed for exam %s", parsed_exam_id
        )
        raise

    logger.info(
        "Result synchronization job finished for exam %s; batches=%s rejected=%s",
        parsed_exam_id,
        batches_processed,
        results_rejected,
    )
