"""Cross-domain invalidation caused by authoritative academic sync changes."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.exams.lineage import latest_exam_revision_clause
from app.domains.exams.models import Exam, ExamRosterStatus, ExamStatus


class SyncInvalidationRepository:
    """Invalidate local derived state when synchronized academic truth changes.

    Candidate rosters are derived from synchronized enrollment and elective
    selection truth. Once an exam is ACTIVE the roster is execution evidence and
    must not be rewritten by later Cloud changes. SEALED + READY rosters on the
    latest revision, however, are still pre-execution materializations and must
    be refreshed when eligibility truth changes. Superseded revisions are
    historical evidence and are never invalidated by later academic sync.

    The sync transaction already owns the global sync advisory lock. Candidate
    roster builders historically lock the exam row before waiting for that sync
    lock, so waiting on the same exam row here would create an inverse lock order.
    We therefore lock only currently available exam rows with SKIP LOCKED. A
    skipped exam is being changed by another transaction; after sync commits that
    transaction must acquire the sync lock before reading academic truth, so it
    will materialize from the newly committed state itself.
    """

    @staticmethod
    async def mark_pre_execution_rosters_stale(db: AsyncSession) -> int:
        locked_ids = list(
            (
                await db.execute(
                    select(Exam.id)
                    .where(
                        Exam.status == ExamStatus.SEALED,
                        Exam.roster_status == ExamRosterStatus.READY,
                        latest_exam_revision_clause(),
                    )
                    .with_for_update(of=Exam, skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not locked_ids:
            return 0

        result = await db.execute(
            update(Exam)
            .where(Exam.id.in_(locked_ids))
            .values(
                roster_status=ExamRosterStatus.STALE,
                roster_error=(
                    "Synchronized academic eligibility changed; candidate roster "
                    "must be reconciled before activation"
                ),
            )
        )
        return int(result.rowcount or 0)
