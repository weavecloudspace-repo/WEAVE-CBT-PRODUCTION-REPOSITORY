"""Persistence operations for candidate examination attempts.

The repository persists attempt state, interruptions, stable presentation
allocations, answers and selections. Timing policy, lifecycle transitions,
answer sequencing policy, scoring, authorization and transaction boundaries
belong to services.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.attempts.models import (
    AttemptAnswer,
    AttemptAnswerSelection,
    AttemptInterruption,
    AttemptOptionAllocation,
    AttemptQuestionAllocation,
    AttemptStatus,
    ExamAttempt,
)
from app.domains.candidates.models import ExamCandidate
from app.domains.exams.models import ExamQuestionOption
from app.domains.questions.models import QuestionOption


class AttemptRepository:
    """Provide database operations for attempts and persisted answer state."""

    @staticmethod
    async def add_attempt(db: AsyncSession, attempt: ExamAttempt) -> ExamAttempt:
        db.add(attempt)
        await db.flush()
        return attempt

    @staticmethod
    async def save_attempt(db: AsyncSession, attempt: ExamAttempt) -> ExamAttempt:
        db.add(attempt)
        await db.flush()
        return attempt

    @staticmethod
    async def get_attempt_by_id(
        db: AsyncSession,
        attempt_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamAttempt | None:
        query = select(ExamAttempt).where(ExamAttempt.id == attempt_id)
        if lock:
            query = query.with_for_update(of=ExamAttempt)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_attempt_by_candidate_id(
        db: AsyncSession,
        candidate_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamAttempt | None:
        query = select(ExamAttempt).where(ExamAttempt.candidate_id == candidate_id)
        if lock:
            query = query.with_for_update(of=ExamAttempt)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_attempts(
        db: AsyncSession,
        *,
        exam_id: UUID | None = None,
        statuses: Sequence[AttemptStatus] | None = None,
        heartbeat_before: datetime | None = None,
        limit: int | None = None,
        lock: bool = False,
        skip_locked: bool = False,
    ) -> list[ExamAttempt]:
        query = select(ExamAttempt)
        if exam_id is not None:
            query = query.join(
                ExamCandidate,
                ExamCandidate.id == ExamAttempt.candidate_id,
            ).where(ExamCandidate.exam_id == exam_id)
        if statuses is not None:
            status_values = list(statuses)
            if not status_values:
                return []
            query = query.where(ExamAttempt.status.in_(status_values))
        if heartbeat_before is not None:
            query = query.where(ExamAttempt.last_heartbeat_at < heartbeat_before)
        query = query.order_by(
            ExamAttempt.last_heartbeat_at.asc(),
            ExamAttempt.id.asc(),
        )
        if limit is not None:
            query = query.limit(limit)
        if lock:
            query = query.with_for_update(
                of=ExamAttempt,
                skip_locked=skip_locked,
            )
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def count_attempts_for_exam(
        db: AsyncSession,
        exam_id: UUID,
        *,
        status: AttemptStatus | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ExamAttempt)
            .join(
                ExamCandidate,
                ExamCandidate.id == ExamAttempt.candidate_id,
            )
            .where(ExamCandidate.exam_id == exam_id)
        )
        if status is not None:
            query = query.where(ExamAttempt.status == status)
        return int((await db.execute(query)).scalar_one() or 0)

    @staticmethod
    async def add_interruption(
        db: AsyncSession,
        interruption: AttemptInterruption,
    ) -> AttemptInterruption:
        db.add(interruption)
        await db.flush()
        return interruption

    @staticmethod
    async def save_interruption(
        db: AsyncSession,
        interruption: AttemptInterruption,
    ) -> AttemptInterruption:
        db.add(interruption)
        await db.flush()
        return interruption

    @staticmethod
    async def get_interruption_by_id(
        db: AsyncSession,
        interruption_id: UUID,
        *,
        lock: bool = False,
    ) -> AttemptInterruption | None:
        query = select(AttemptInterruption).where(
            AttemptInterruption.id == interruption_id
        )
        if lock:
            query = query.with_for_update(of=AttemptInterruption)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_open_interruption_for_attempt(
        db: AsyncSession,
        attempt_id: UUID,
        *,
        lock: bool = False,
    ) -> AttemptInterruption | None:
        query = (
            select(AttemptInterruption)
            .where(
                AttemptInterruption.attempt_id == attempt_id,
                AttemptInterruption.resumed_at.is_(None),
            )
            .order_by(
                AttemptInterruption.interrupted_at.desc(),
                AttemptInterruption.id.desc(),
            )
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=AttemptInterruption)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_interruptions_for_attempt(
        db: AsyncSession,
        attempt_id: UUID,
    ) -> list[AttemptInterruption]:
        result = await db.execute(
            select(AttemptInterruption)
            .where(AttemptInterruption.attempt_id == attempt_id)
            .order_by(
                AttemptInterruption.interrupted_at.asc(),
                AttemptInterruption.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_question_allocation(
        db: AsyncSession,
        allocation: AttemptQuestionAllocation,
    ) -> AttemptQuestionAllocation:
        db.add(allocation)
        await db.flush()
        return allocation

    @staticmethod
    async def add_question_allocations(
        db: AsyncSession,
        allocations: Sequence[AttemptQuestionAllocation],
    ) -> list[AttemptQuestionAllocation]:
        rows = list(allocations)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_question_allocation_by_id(
        db: AsyncSession,
        allocation_id: UUID,
        *,
        lock: bool = False,
    ) -> AttemptQuestionAllocation | None:
        query = select(AttemptQuestionAllocation).where(
            AttemptQuestionAllocation.id == allocation_id
        )
        if lock:
            query = query.with_for_update(of=AttemptQuestionAllocation)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_question_allocation(
        db: AsyncSession,
        attempt_id: UUID,
        exam_question_id: UUID,
        *,
        lock: bool = False,
    ) -> AttemptQuestionAllocation | None:
        query = select(AttemptQuestionAllocation).where(
            AttemptQuestionAllocation.attempt_id == attempt_id,
            AttemptQuestionAllocation.exam_question_id == exam_question_id,
        )
        if lock:
            query = query.with_for_update(of=AttemptQuestionAllocation)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_question_allocations(
        db: AsyncSession,
        attempt_id: UUID,
    ) -> list[AttemptQuestionAllocation]:
        result = await db.execute(
            select(AttemptQuestionAllocation)
            .where(AttemptQuestionAllocation.attempt_id == attempt_id)
            .order_by(
                AttemptQuestionAllocation.position.asc(),
                AttemptQuestionAllocation.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_question_allocations(
        db: AsyncSession,
        attempt_id: UUID,
    ) -> int:
        value = await db.scalar(
            select(func.count())
            .select_from(AttemptQuestionAllocation)
            .where(AttemptQuestionAllocation.attempt_id == attempt_id)
        )
        return int(value or 0)

    @staticmethod
    async def _hydrate_option_media(
        db: AsyncSession,
        rows: list[AttemptOptionAllocation],
    ) -> None:
        exam_option_ids = [
            row.exam_question_option_id
            for row in rows
            if row.exam_question_option_id is not None
        ]
        source_option_ids = [
            row.source_question_option_id
            for row in rows
            if row.source_question_option_id is not None
        ]

        exam_media: dict[UUID, UUID | None] = {}
        if exam_option_ids:
            exam_rows = (
                (
                    await db.execute(
                        select(ExamQuestionOption).where(
                            ExamQuestionOption.id.in_(exam_option_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            exam_media = {row.id: row.image_asset_id for row in exam_rows}

        source_media: dict[UUID, UUID | None] = {}
        if source_option_ids:
            source_rows = (
                (
                    await db.execute(
                        select(QuestionOption).where(
                            QuestionOption.id.in_(source_option_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            source_media = {row.id: row.image_asset_id for row in source_rows}

        for row in rows:
            if row.exam_question_option_id is not None:
                row.image_asset_id = exam_media.get(row.exam_question_option_id)
            elif row.source_question_option_id is not None:
                row.image_asset_id = source_media.get(row.source_question_option_id)

    @staticmethod
    async def add_option_allocation(
        db: AsyncSession,
        allocation: AttemptOptionAllocation,
    ) -> AttemptOptionAllocation:
        rows = await AttemptRepository.add_option_allocations(db, [allocation])
        return rows[0]

    @staticmethod
    async def add_option_allocations(
        db: AsyncSession,
        allocations: Sequence[AttemptOptionAllocation],
    ) -> list[AttemptOptionAllocation]:
        rows = list(allocations)
        if rows:
            await AttemptRepository._hydrate_option_media(db, rows)
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_option_allocation_by_id(
        db: AsyncSession,
        allocation_id: UUID,
        *,
        lock: bool = False,
    ) -> AttemptOptionAllocation | None:
        query = select(AttemptOptionAllocation).where(
            AttemptOptionAllocation.id == allocation_id
        )
        if lock:
            query = query.with_for_update(of=AttemptOptionAllocation)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_option_allocation(
        db: AsyncSession,
        attempt_question_id: UUID,
        exam_question_option_id: UUID,
    ) -> AttemptOptionAllocation | None:
        return (
            await db.execute(
                select(AttemptOptionAllocation).where(
                    AttemptOptionAllocation.attempt_question_id == attempt_question_id,
                    AttemptOptionAllocation.exam_question_option_id
                    == exam_question_option_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_option_allocations(
        db: AsyncSession,
        attempt_question_id: UUID,
    ) -> list[AttemptOptionAllocation]:
        result = await db.execute(
            select(AttemptOptionAllocation)
            .where(AttemptOptionAllocation.attempt_question_id == attempt_question_id)
            .order_by(
                AttemptOptionAllocation.position.asc(),
                AttemptOptionAllocation.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_option_allocations_for_questions(
        db: AsyncSession,
        attempt_question_ids: Sequence[UUID],
    ) -> list[AttemptOptionAllocation]:
        question_ids = list(dict.fromkeys(attempt_question_ids))
        if not question_ids:
            return []
        result = await db.execute(
            select(AttemptOptionAllocation)
            .where(AttemptOptionAllocation.attempt_question_id.in_(question_ids))
            .order_by(
                AttemptOptionAllocation.attempt_question_id.asc(),
                AttemptOptionAllocation.position.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_answer(
        db: AsyncSession,
        answer: AttemptAnswer,
    ) -> AttemptAnswer:
        db.add(answer)
        await db.flush()
        return answer

    @staticmethod
    async def add_answers(
        db: AsyncSession,
        answers: Sequence[AttemptAnswer],
    ) -> list[AttemptAnswer]:
        rows = list(answers)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def save_answer(
        db: AsyncSession,
        answer: AttemptAnswer,
    ) -> AttemptAnswer:
        db.add(answer)
        await db.flush()
        return answer

    @staticmethod
    async def get_answer_by_id(
        db: AsyncSession,
        answer_id: UUID,
        *,
        lock: bool = False,
    ) -> AttemptAnswer | None:
        query = select(AttemptAnswer).where(AttemptAnswer.id == answer_id)
        if lock:
            query = query.with_for_update(of=AttemptAnswer)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_answer_for_question(
        db: AsyncSession,
        attempt_question_id: UUID,
        *,
        lock: bool = False,
    ) -> AttemptAnswer | None:
        query = select(AttemptAnswer).where(
            AttemptAnswer.attempt_question_id == attempt_question_id
        )
        if lock:
            query = query.with_for_update(of=AttemptAnswer)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_answers_for_attempt(
        db: AsyncSession,
        attempt_id: UUID,
    ) -> list[AttemptAnswer]:
        result = await db.execute(
            select(AttemptAnswer)
            .join(
                AttemptQuestionAllocation,
                AttemptQuestionAllocation.id == AttemptAnswer.attempt_question_id,
            )
            .where(AttemptQuestionAllocation.attempt_id == attempt_id)
            .order_by(
                AttemptQuestionAllocation.position.asc(),
                AttemptAnswer.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_selection(
        db: AsyncSession,
        selection: AttemptAnswerSelection,
    ) -> AttemptAnswerSelection:
        db.add(selection)
        await db.flush()
        return selection

    @staticmethod
    async def add_selections(
        db: AsyncSession,
        selections: Sequence[AttemptAnswerSelection],
    ) -> list[AttemptAnswerSelection]:
        rows = list(selections)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_selection(
        db: AsyncSession,
        answer_id: UUID,
        attempt_option_id: UUID,
    ) -> AttemptAnswerSelection | None:
        return (
            await db.execute(
                select(AttemptAnswerSelection).where(
                    AttemptAnswerSelection.answer_id == answer_id,
                    AttemptAnswerSelection.attempt_option_id == attempt_option_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_selections_for_answer(
        db: AsyncSession,
        answer_id: UUID,
    ) -> list[AttemptAnswerSelection]:
        result = await db.execute(
            select(AttemptAnswerSelection)
            .where(AttemptAnswerSelection.answer_id == answer_id)
            .order_by(
                AttemptAnswerSelection.created_at.asc(),
                AttemptAnswerSelection.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_selections_for_answers(
        db: AsyncSession,
        answer_ids: Sequence[UUID],
    ) -> list[AttemptAnswerSelection]:
        ids = list(dict.fromkeys(answer_ids))
        if not ids:
            return []
        result = await db.execute(
            select(AttemptAnswerSelection)
            .where(AttemptAnswerSelection.answer_id.in_(ids))
            .order_by(
                AttemptAnswerSelection.answer_id.asc(),
                AttemptAnswerSelection.created_at.asc(),
                AttemptAnswerSelection.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def remove_selection(
        db: AsyncSession,
        selection: AttemptAnswerSelection,
    ) -> None:
        await db.delete(selection)
        await db.flush()

    @staticmethod
    async def clear_selections_for_answer(
        db: AsyncSession,
        answer_id: UUID,
    ) -> None:
        await db.execute(
            delete(AttemptAnswerSelection).where(
                AttemptAnswerSelection.answer_id == answer_id
            )
        )
        await db.flush()
