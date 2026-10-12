"""Persistence helpers for reviewed AI question import idempotency."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.questions.ai_models import QuestionAIImportBatch, QuestionAIImportItem
from app.domains.questions.models import Question


class QuestionAIRepository:
    @staticmethod
    async def get_import_batch_by_draft_id(
        db: AsyncSession,
        draft_id: UUID,
    ) -> QuestionAIImportBatch | None:
        return (
            await db.execute(
                select(QuestionAIImportBatch).where(
                    QuestionAIImportBatch.draft_id == draft_id
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def add_import_batch(
        db: AsyncSession,
        batch: QuestionAIImportBatch,
    ) -> QuestionAIImportBatch:
        db.add(batch)
        await db.flush()
        return batch

    @staticmethod
    async def add_import_item(
        db: AsyncSession,
        item: QuestionAIImportItem,
    ) -> QuestionAIImportItem:
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def list_questions_for_import_batch(
        db: AsyncSession,
        batch_id: UUID,
    ) -> list[Question]:
        result = await db.execute(
            select(Question)
            .join(
                QuestionAIImportItem,
                QuestionAIImportItem.question_id == Question.id,
            )
            .where(QuestionAIImportItem.batch_id == batch_id)
            .order_by(QuestionAIImportItem.position.asc())
        )
        return list(result.scalars().all())
