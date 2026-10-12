"""Low-latency delivery for durable candidate-roster reconciliation work.

PostgreSQL remains authoritative. Academic synchronization marks affected
pre-execution rosters STALE inside its own transaction; only after that
transaction commits do we ask ARQ to deliver reconciliation work immediately.
The periodic maintenance sweep remains the recovery path if Redis is unavailable
or an enqueue is otherwise lost.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.database import async_session_factory
from app.domains.exams.lineage import latest_exam_revision_clause
from app.domains.exams.models import Exam, ExamRosterStatus, ExamStatus
from app.domains.sync.schemas import SyncReconcileResponse
from app.workers.producer import arq_producer, roster_reconcile_job_id

logger = logging.getLogger(__name__)


async def enqueue_stale_roster_reconciliations() -> int:
    """Immediately enqueue every durable current SEALED + STALE roster.

    Superseded revisions are historical evidence and are deliberately excluded
    even if an older deployment left one in STALE state.

    The query runs in a fresh session so this function can only observe roster
    invalidations that have already committed. Each automatic reconciliation is
    deduplicated by exam ID + current roster version. Repeated discovery of the
    same stale generation collapses to one ARQ job, while a later enrollment
    change against a newer roster version receives a fresh job ID immediately.

    Delivery is best-effort. A database/Redis failure here must not turn a
    successfully committed academic sync into an application failure because
    the periodic maintenance sweep can reconstruct this work from PostgreSQL.
    """

    try:
        async with async_session_factory() as db:
            roster_generations = list(
                (
                    await db.execute(
                        select(Exam.id, Exam.roster_version)
                        .where(
                            Exam.status == ExamStatus.SEALED,
                            Exam.roster_status == ExamRosterStatus.STALE,
                            latest_exam_revision_clause(),
                        )
                        .order_by(Exam.updated_at.asc(), Exam.id.asc())
                    )
                )
                .tuples()
                .all()
            )
            await db.rollback()
    except Exception:
        logger.exception(
            "Could not discover stale rosters for immediate reconciliation; "
            "maintenance recovery will retry later"
        )
        return 0

    queued = 0
    for exam_id, roster_version in roster_generations:
        delivered = await arq_producer.enqueue(
            "reconcile_exam_roster",
            str(exam_id),
            _job_id=roster_reconcile_job_id(exam_id, roster_version),
        )
        if delivered:
            queued += 1

    if roster_generations:
        logger.info(
            "Immediate roster reconciliation delivery requested for %s stale exam(s); %s accepted by ARQ",
            len(roster_generations),
            queued,
        )

    return queued


async def enqueue_roster_reconciliation_after_sync(
    result: SyncReconcileResponse,
) -> int:
    """Deliver stale-roster work only when synchronization changed local truth."""

    if not result.bootstrapped and result.changes_applied <= 0:
        return 0

    return await enqueue_stale_roster_reconciliations()
