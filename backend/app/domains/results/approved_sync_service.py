"""Approval-gated facade for result synchronization."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.exams.execution_service import ExamExecutionService
from app.domains.results.sync_service import result_sync_service


class ApprovedResultSyncService:
    """Refuse external result transfer unless the school approved the sitting."""

    @staticmethod
    async def sync_next_batch(
        db: AsyncSession,
        *,
        exam_id: UUID,
        limit: int = 1000,
    ):
        approved = await ExamExecutionService.results_are_approved(
            db,
            exam_id=exam_id,
        )
        await db.rollback()
        if not approved:
            return None
        return await result_sync_service.sync_next_batch(
            db,
            exam_id=exam_id,
            limit=limit,
        )


approved_result_sync_service = ApprovedResultSyncService()
