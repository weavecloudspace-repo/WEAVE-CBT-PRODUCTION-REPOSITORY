"""Read-only runtime helpers used by AttemptService timing calculations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.exams.models import ExamSuspension
from app.domains.exams.repository import ExamRepository


class AttemptRuntimeRepository:
    @staticmethod
    async def list_exam_suspensions(
        db: AsyncSession,
        exam_id: UUID,
    ) -> list[ExamSuspension]:
        return await ExamRepository.list_suspensions_for_exam(db, exam_id)
