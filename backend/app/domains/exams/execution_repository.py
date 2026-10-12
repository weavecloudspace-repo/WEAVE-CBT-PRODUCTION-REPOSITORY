"""Persistence helpers for durable exam execution/result-review control."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.exams.execution_models import ExamExecutionControl


class ExamExecutionRepository:
    @staticmethod
    async def get_control(
        db: AsyncSession,
        exam_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamExecutionControl | None:
        query = select(ExamExecutionControl).where(
            ExamExecutionControl.exam_id == exam_id
        )
        if lock:
            query = query.with_for_update(of=ExamExecutionControl)
        return (await db.execute(query)).scalar_one_or_none()

    @classmethod
    async def get_or_create_control(
        cls,
        db: AsyncSession,
        exam_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamExecutionControl:
        control = await cls.get_control(db, exam_id, lock=lock)
        if control is not None:
            return control
        control = ExamExecutionControl(exam_id=exam_id)
        db.add(control)
        await db.flush()
        return control

    @staticmethod
    async def save_control(
        db: AsyncSession,
        control: ExamExecutionControl,
    ) -> ExamExecutionControl:
        db.add(control)
        await db.flush()
        return control
