"""Persistence operations for immutable locally stored media assets."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.attempts.models import (
    AttemptOptionAllocation,
    AttemptQuestionAllocation,
)
from app.domains.exams.models import ExamQuestion, ExamQuestionOption
from app.domains.media.models import MediaAsset
from app.domains.questions.models import Question, QuestionOption


class MediaRepository:
    @staticmethod
    async def add_asset(
        db: AsyncSession,
        asset: MediaAsset,
    ) -> MediaAsset:
        """Persist MediaAsset metadata without committing."""

        db.add(asset)
        await db.flush()
        await db.refresh(asset)
        return asset

    @staticmethod
    async def get_asset_by_id(
        db: AsyncSession,
        asset_id: UUID,
        *,
        lock: bool = False,
    ) -> MediaAsset | None:
        query = select(MediaAsset).where(MediaAsset.id == asset_id)
        if lock:
            query = query.with_for_update(of=MediaAsset)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_asset_by_storage_key(
        db: AsyncSession,
        storage_key: str,
    ) -> MediaAsset | None:
        result = await db.execute(
            select(MediaAsset).where(MediaAsset.storage_key == storage_key)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _exists_reference(
        db: AsyncSession,
        predicate,
    ) -> bool:
        result = await db.execute(select(exists().where(predicate)))
        return bool(result.scalar())

    @staticmethod
    async def is_referenced_by_question(
        db: AsyncSession,
        asset_id: UUID,
    ) -> bool:
        if await MediaRepository._exists_reference(
            db,
            Question.image_asset_id == asset_id,
        ):
            return True
        return await MediaRepository._exists_reference(
            db,
            QuestionOption.image_asset_id == asset_id,
        )

    @staticmethod
    async def is_referenced_by_exam_question(
        db: AsyncSession,
        asset_id: UUID,
    ) -> bool:
        if await MediaRepository._exists_reference(
            db,
            ExamQuestion.image_asset_id == asset_id,
        ):
            return True
        return await MediaRepository._exists_reference(
            db,
            ExamQuestionOption.image_asset_id == asset_id,
        )

    @staticmethod
    async def is_referenced_by_attempt_question(
        db: AsyncSession,
        asset_id: UUID,
    ) -> bool:
        if await MediaRepository._exists_reference(
            db,
            AttemptQuestionAllocation.image_asset_id == asset_id,
        ):
            return True
        return await MediaRepository._exists_reference(
            db,
            AttemptOptionAllocation.image_asset_id == asset_id,
        )

    @staticmethod
    async def is_referenced(
        db: AsyncSession,
        asset_id: UUID,
    ) -> bool:
        if await MediaRepository.is_referenced_by_question(db, asset_id):
            return True
        if await MediaRepository.is_referenced_by_exam_question(db, asset_id):
            return True
        return await MediaRepository.is_referenced_by_attempt_question(db, asset_id)

    @staticmethod
    async def delete_asset(
        db: AsyncSession,
        asset: MediaAsset,
    ) -> None:
        """Delete metadata after the service has established reference safety."""

        await db.delete(asset)
        await db.flush()
