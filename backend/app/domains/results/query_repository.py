"""Read-optimized queries for administrator result review screens."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.candidates.models import ExamCandidate
from app.domains.exams.execution_models import ExamExecutionControl
from app.domains.exams.models import Exam, ExamStatus
from app.domains.results.models import ExamResult, ResultSyncStatus


class ResultQueryRepository:
    """Read-only result queries shaped for review and filtering workflows."""

    @staticmethod
    async def list_exam_result_rows(
        db: AsyncSession,
        *,
        exam_id: UUID,
        search: str | None = None,
        sync_status: ResultSyncStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[tuple[ExamResult, ExamCandidate]]:
        query = (
            select(ExamResult, ExamCandidate)
            .join(ExamCandidate, ExamCandidate.id == ExamResult.candidate_id)
            .where(ExamResult.exam_id == exam_id)
        )
        query = ResultQueryRepository._apply_result_filters(
            query,
            search=search,
            sync_status=sync_status,
        )
        query = (
            query.order_by(
                ExamCandidate.display_name.asc(),
                ExamCandidate.admission_number.asc(),
                ExamResult.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list((await db.execute(query)).all())

    @staticmethod
    async def count_exam_result_rows(
        db: AsyncSession,
        *,
        exam_id: UUID,
        search: str | None = None,
        sync_status: ResultSyncStatus | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ExamResult)
            .join(ExamCandidate, ExamCandidate.id == ExamResult.candidate_id)
            .where(ExamResult.exam_id == exam_id)
        )
        query = ResultQueryRepository._apply_result_filters(
            query,
            search=search,
            sync_status=sync_status,
        )
        return int((await db.execute(query)).scalar_one() or 0)

    @staticmethod
    def _apply_result_filters(
        query, *, search: str | None, sync_status: ResultSyncStatus | None
    ):
        if sync_status is not None:
            query = query.where(ExamResult.sync_status == sync_status)
        needle = (search or "").strip()
        if needle:
            pattern = f"%{needle}%"
            query = query.where(
                or_(
                    ExamCandidate.admission_number.ilike(pattern),
                    ExamCandidate.display_name.ilike(pattern),
                )
            )
        return query

    @staticmethod
    async def list_review_sets(
        db: AsyncSession,
        *,
        exam_ids: Sequence[UUID] | None = None,
    ) -> list[dict]:
        """Return one aggregate row per terminal examination result set."""

        result_count = func.count(ExamResult.id)
        pending_count = func.count(ExamResult.id).filter(
            ExamResult.sync_status == ResultSyncStatus.PENDING,
            ExamResult.voided_at.is_(None),
        )
        syncing_count = func.count(ExamResult.id).filter(
            ExamResult.sync_status == ResultSyncStatus.SYNCING
        )
        synced_count = func.count(ExamResult.id).filter(
            ExamResult.sync_status == ResultSyncStatus.SYNCED
        )
        failed_count = func.count(ExamResult.id).filter(
            ExamResult.sync_status == ResultSyncStatus.FAILED,
            ExamResult.voided_at.is_(None),
        )
        voided_count = func.count(ExamResult.id).filter(
            ExamResult.voided_at.is_not(None)
        )
        completed_at = func.coalesce(Exam.closed_at, Exam.cancelled_at)

        query = (
            select(
                Exam.id.label("exam_id"),
                completed_at.label("completed_at"),
                ExamExecutionControl.result_disposition.label("result_disposition"),
                ExamExecutionControl.results_decided_at.label("results_decided_at"),
                ExamExecutionControl.results_decision_reason.label(
                    "results_decision_reason"
                ),
                result_count.label("result_count"),
                pending_count.label("pending_count"),
                syncing_count.label("syncing_count"),
                synced_count.label("synced_count"),
                failed_count.label("failed_count"),
                voided_count.label("voided_count"),
            )
            .outerjoin(ExamExecutionControl, ExamExecutionControl.exam_id == Exam.id)
            .outerjoin(ExamResult, ExamResult.exam_id == Exam.id)
            .where(Exam.status.in_([ExamStatus.CLOSED, ExamStatus.CANCELLED]))
            .group_by(
                Exam.id,
                Exam.closed_at,
                Exam.cancelled_at,
                ExamExecutionControl.result_disposition,
                ExamExecutionControl.results_decided_at,
                ExamExecutionControl.results_decision_reason,
            )
            .order_by(completed_at.desc().nullslast(), Exam.id.desc())
        )
        if exam_ids is not None:
            ids = list(exam_ids)
            if not ids:
                return []
            query = query.where(Exam.id.in_(ids))

        rows = (await db.execute(query)).mappings().all()
        return [dict(row) for row in rows]
