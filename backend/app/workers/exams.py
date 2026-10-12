"""ARQ jobs for durable examination lifecycle finalization."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.database import async_session_factory
from app.domains.attempts.guarded_service import AttemptService
from app.domains.attempts.models import AttemptStatus
from app.domains.attempts.repository import AttemptRepository
from app.domains.exams.execution_service import ExamExecutionService

logger = logging.getLogger(__name__)

EXPIRED_ATTEMPT_SCAN_LIMIT = 5000


def _parse_exam_id(value: str, *, job_name: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{job_name} received an invalid exam ID") from exc


async def finalize_exam_close(_ctx: dict, exam_id: str) -> None:
    parsed_exam_id = _parse_exam_id(exam_id, job_name="finalize_exam_close")
    try:
        async with async_session_factory() as db:
            await ExamExecutionService.finalize_close(db, exam_id=parsed_exam_id)
    except Exception as exc:
        logger.exception("Exam close finalization failed for %s", parsed_exam_id)
        async with async_session_factory() as db:
            await ExamExecutionService.mark_operation_error(
                db,
                exam_id=parsed_exam_id,
                message=f"{type(exc).__name__}: {exc}",
            )
        raise


async def finalize_exam_cancellation(_ctx: dict, exam_id: str) -> None:
    parsed_exam_id = _parse_exam_id(exam_id, job_name="finalize_exam_cancellation")
    try:
        async with async_session_factory() as db:
            await ExamExecutionService.finalize_cancellation(
                db,
                exam_id=parsed_exam_id,
            )
    except Exception as exc:
        logger.exception("Exam cancellation finalization failed for %s", parsed_exam_id)
        async with async_session_factory() as db:
            await ExamExecutionService.mark_operation_error(
                db,
                exam_id=parsed_exam_id,
                message=f"{type(exc).__name__}: {exc}",
            )
        raise


async def evaluate_exam_completion(ctx: dict, exam_id: str) -> None:
    parsed_exam_id = _parse_exam_id(exam_id, job_name="evaluate_exam_completion")
    async with async_session_factory() as db:
        requested = await ExamExecutionService.evaluate_automatic_close(
            db,
            exam_id=parsed_exam_id,
        )
    if not requested:
        return

    # Complete the automatic close in the same worker invocation. PostgreSQL
    # state makes this safe to retry if this process stops between the two steps.
    await finalize_exam_close(ctx, exam_id)


async def finalize_expired_attempts(ctx: dict) -> dict[str, int]:
    """Submit timed-out attempts even when the candidate browser disappears.

    The first pass is an inexpensive in-memory deadline prefilter. It may include
    attempts protected by whole-exam suspension; each candidate is therefore
    rechecked with the authoritative timing calculation under row lock before
    any academic state changes.
    """

    now = datetime.now(UTC)
    possible_expired_ids: list[UUID] = []
    async with async_session_factory() as db:
        attempts = await AttemptRepository.list_attempts(
            db,
            statuses=[AttemptStatus.IN_PROGRESS],
            limit=EXPIRED_ATTEMPT_SCAN_LIMIT,
        )
        # Rollback expires ORM attributes, so read timing fields and retain only
        # plain IDs before ending the scan transaction.
        for attempt in attempts:
            if attempt.active_since is None:
                continue
            uncheckpointed_allowance = max(
                0,
                attempt.time_limit_seconds - attempt.elapsed_seconds,
            )
            if (
                attempt.active_since + timedelta(seconds=uncheckpointed_allowance)
                <= now
            ):
                possible_expired_ids.append(attempt.id)
        await db.rollback()

    finalized = 0
    affected_exam_ids: set[UUID] = set()
    for attempt_id in possible_expired_ids:
        try:
            async with async_session_factory() as db:
                exam_id = await AttemptService.finalize_if_expired(
                    db,
                    attempt_id=attempt_id,
                    at=now,
                )
                if exam_id is not None:
                    affected_exam_ids.add(exam_id)
                # A None exam ID can also be a finalized makeup attempt. Check
                # the durable row after the helper to count all submissions.
                row = await AttemptRepository.get_attempt_by_id(db, attempt_id)
                if row is not None and row.status == AttemptStatus.SUBMITTED:
                    finalized += 1
                await db.rollback()
        except Exception:
            logger.exception("Expired attempt finalization failed for %s", attempt_id)

    for exam_id in sorted(affected_exam_ids, key=str):
        await evaluate_exam_completion(ctx, str(exam_id))

    if finalized:
        logger.info(
            "Finalized %s expired attempt(s) across %s normal exam(s)",
            finalized,
            len(affected_exam_ids),
        )
    return {
        "expired_attempts_scanned": len(possible_expired_ids),
        "expired_attempts_finalized": finalized,
        "completion_exams_rechecked": len(affected_exam_ids),
    }
