"""Persistence operations for locally owned question-bank data."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.questions.models import (
    Question,
    QuestionBank,
    QuestionOption,
    QuestionType,
)


class QuestionRepository:
    @staticmethod
    async def add_bank(db: AsyncSession, bank: QuestionBank) -> QuestionBank:
        db.add(bank)
        await db.flush()
        return bank

    @staticmethod
    async def get_bank_by_id(
        db: AsyncSession,
        bank_id: UUID,
        *,
        lock: bool = False,
    ) -> QuestionBank | None:
        query = select(QuestionBank).where(QuestionBank.id == bank_id)
        if lock:
            query = query.with_for_update(of=QuestionBank)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_bank_by_scope_and_name(
        db: AsyncSession,
        curriculum_subject_id: UUID,
        name: str,
        *,
        lock: bool = False,
    ) -> QuestionBank | None:
        query = select(QuestionBank).where(
            QuestionBank.curriculum_subject_id == curriculum_subject_id,
            QuestionBank.name == name,
        )
        if lock:
            query = query.with_for_update(of=QuestionBank)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_banks(
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID | None = None,
        created_by_actor_id: UUID | None = None,
        active_only: bool = False,
    ) -> list[QuestionBank]:
        query = select(QuestionBank)
        if curriculum_subject_id is not None:
            query = query.where(
                QuestionBank.curriculum_subject_id == curriculum_subject_id
            )
        if created_by_actor_id is not None:
            query = query.where(QuestionBank.created_by_actor_id == created_by_actor_id)
        if active_only:
            query = query.where(QuestionBank.is_active.is_(True))
        result = await db.execute(
            query.order_by(QuestionBank.name.asc(), QuestionBank.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_banks_for_curriculum_subjects(
        db: AsyncSession,
        *,
        curriculum_subject_ids: Sequence[UUID],
        active_only: bool = True,
    ) -> list[QuestionBank]:
        subject_ids = list(dict.fromkeys(curriculum_subject_ids))
        if not subject_ids:
            return []

        query = select(QuestionBank).where(
            QuestionBank.curriculum_subject_id.in_(subject_ids)
        )
        if active_only:
            query = query.where(QuestionBank.is_active.is_(True))

        result = await db.execute(
            query.order_by(QuestionBank.name.asc(), QuestionBank.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def save_bank(db: AsyncSession, bank: QuestionBank) -> QuestionBank:
        db.add(bank)
        await db.flush()
        return bank

    @staticmethod
    async def list_nonempty_bank_ids(
        db: AsyncSession,
        bank_ids: Sequence[UUID],
    ) -> set[UUID]:
        if not bank_ids:
            return set()
        query = (
            select(Question.bank_id).where(Question.bank_id.in_(bank_ids)).distinct()
        )
        return set((await db.execute(query)).scalars().all())

    @staticmethod
    async def delete_bank(db: AsyncSession, bank: QuestionBank) -> None:
        await db.delete(bank)
        await db.flush()

    @staticmethod
    async def add_question(db: AsyncSession, question: Question) -> Question:
        db.add(question)
        await db.flush()
        return question

    @staticmethod
    async def add_questions(
        db: AsyncSession,
        questions: Sequence[Question],
    ) -> list[Question]:
        rows = list(questions)
        if not rows:
            return []
        db.add_all(rows)
        await db.flush()
        return rows

    @staticmethod
    async def get_question_by_id(
        db: AsyncSession,
        question_id: UUID,
        *,
        lock: bool = False,
    ) -> Question | None:
        query = select(Question).where(Question.id == question_id)
        if lock:
            query = query.with_for_update(of=Question)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_questions_for_bank(
        db: AsyncSession,
        bank_id: UUID,
        *,
        question_type: QuestionType | None = None,
        created_by_actor_id: UUID | None = None,
        active_only: bool = False,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Question]:
        query = select(Question).where(Question.bank_id == bank_id)
        if question_type is not None:
            query = query.where(Question.question_type == question_type)
        if created_by_actor_id is not None:
            query = query.where(Question.created_by_actor_id == created_by_actor_id)
        if active_only:
            query = query.where(Question.is_active.is_(True))
        query = query.order_by(Question.created_at.asc(), Question.id.asc()).offset(
            offset
        )
        if limit is not None:
            query = query.limit(limit)
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_questions_for_banks(
        db: AsyncSession,
        bank_ids: Sequence[UUID],
        *,
        question_type: QuestionType | None = None,
        created_by_actor_id: UUID | None = None,
        active_only: bool = False,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Question]:
        """Return questions across a bounded set of banks for management views."""

        unique_bank_ids = list(dict.fromkeys(bank_ids))
        if not unique_bank_ids:
            return []

        query = select(Question).where(Question.bank_id.in_(unique_bank_ids))
        if question_type is not None:
            query = query.where(Question.question_type == question_type)
        if created_by_actor_id is not None:
            query = query.where(Question.created_by_actor_id == created_by_actor_id)
        if active_only:
            query = query.where(Question.is_active.is_(True))

        query = query.order_by(Question.created_at.asc(), Question.id.asc()).offset(
            offset
        )
        if limit is not None:
            query = query.limit(limit)
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_questions_by_ids(
        db: AsyncSession,
        question_ids: Sequence[UUID],
        *,
        active_only: bool = False,
        lock: bool = False,
    ) -> list[Question]:
        if not question_ids:
            return []
        query = select(Question).where(Question.id.in_(question_ids))
        if active_only:
            query = query.where(Question.is_active.is_(True))

        if lock:
            query = query.with_for_update(of=Question)
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def count_questions_for_bank(
        db: AsyncSession,
        bank_id: UUID,
        *,
        active_only: bool = False,
    ) -> int:
        query = (
            select(func.count())
            .select_from(Question)
            .where(Question.bank_id == bank_id)
        )
        if active_only:
            query = query.where(Question.is_active.is_(True))
        return int((await db.execute(query)).scalar_one() or 0)

    @staticmethod
    async def save_question(db: AsyncSession, question: Question) -> Question:
        db.add(question)
        await db.flush()
        return question

    @staticmethod
    async def delete_question(db: AsyncSession, question: Question) -> None:
        await db.delete(question)
        await db.flush()

    @staticmethod
    async def add_option(db: AsyncSession, option: QuestionOption) -> QuestionOption:
        db.add(option)
        await db.flush()
        return option

    @staticmethod
    async def add_options(
        db: AsyncSession,
        options: Sequence[QuestionOption],
    ) -> list[QuestionOption]:
        rows = list(options)
        if not rows:
            return []
        db.add_all(rows)
        await db.flush()
        return rows

    @staticmethod
    async def get_option_by_id(
        db: AsyncSession,
        option_id: UUID,
    ) -> QuestionOption | None:
        return (
            await db.execute(
                select(QuestionOption).where(QuestionOption.id == option_id)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_options_for_question(
        db: AsyncSession,
        question_id: UUID,
    ) -> list[QuestionOption]:
        result = await db.execute(
            select(QuestionOption)
            .where(QuestionOption.question_id == question_id)
            .order_by(QuestionOption.position.asc(), QuestionOption.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_options_for_questions(
        db: AsyncSession,
        question_ids: Sequence[UUID],
    ) -> list[QuestionOption]:
        if not question_ids:
            return []
        result = await db.execute(
            select(QuestionOption)
            .where(QuestionOption.question_id.in_(question_ids))
            .order_by(QuestionOption.question_id.asc(), QuestionOption.position.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def remove_options_for_question(
        db: AsyncSession,
        question_id: UUID,
    ) -> None:
        await db.execute(
            delete(QuestionOption).where(QuestionOption.question_id == question_id)
        )
        await db.flush()
