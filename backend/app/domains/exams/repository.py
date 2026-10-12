"""Persistence operations for locally owned examination data.

Repositories only perform database reads/writes and row locking. Examination
authorization, lifecycle rules, question-selection policy, revision policy,
roster policy, and transaction boundaries belong to services.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domains.academics.models import Curriculum, CurriculumSubject
from app.domains.exams.models import (
    Exam,
    ExamInvigilator,
    ExamQuestion,
    ExamQuestionOption,
    ExamQuestionSelection,
    ExamRosterStatus,
    ExamStatus,
    ExamSuspension,
    ExamTargetClass,
)


class ExamRepository:
    """Provide persistence operations for exams and their owned child rows."""

    @staticmethod
    async def add_exam(db: AsyncSession, exam: Exam) -> Exam:
        db.add(exam)
        await db.flush()
        return exam

    @staticmethod
    async def save_exam(db: AsyncSession, exam: Exam) -> Exam:
        db.add(exam)
        await db.flush()
        return exam

    @staticmethod
    async def delete_exam(db: AsyncSession, exam: Exam) -> None:
        await db.delete(exam)
        await db.flush()

    @staticmethod
    async def get_exam_by_id(
        db: AsyncSession,
        exam_id: UUID,
        *,
        lock: bool = False,
    ) -> Exam | None:
        query = select(Exam).where(Exam.id == exam_id)
        if lock:
            query = query.with_for_update(of=Exam)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_exam_by_calendar_event_id(
        db: AsyncSession,
        weave_calendar_event_id: str,
        *,
        lock: bool = False,
    ) -> Exam | None:
        query = select(Exam).where(
            Exam.weave_calendar_event_id == weave_calendar_event_id
        )
        if lock:
            query = query.with_for_update(of=Exam)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_exam_revision(
        db: AsyncSession,
        *,
        term_id: UUID,
        curriculum_subject_id: UUID,
        assessment_component_id: UUID,
        title: str | None = None,
        revision_number: int,
        lock: bool = False,
    ) -> Exam | None:
        """Return one shared paper revision for its academic assessment scope.

        title is accepted for compatibility with older callers but is deliberately
        not part of exam identity.
        """
        query = select(Exam).where(
            Exam.term_id == term_id,
            Exam.curriculum_subject_id == curriculum_subject_id,
            Exam.assessment_component_id == assessment_component_id,
            Exam.revision_number == revision_number,
        )
        if lock:
            query = query.with_for_update(of=Exam)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_latest_exam_revision(
        db: AsyncSession,
        *,
        term_id: UUID,
        curriculum_subject_id: UUID,
        assessment_component_id: UUID,
        title: str | None = None,
        lock: bool = False,
    ) -> Exam | None:
        query = (
            select(Exam)
            .where(
                Exam.term_id == term_id,
                Exam.curriculum_subject_id == curriculum_subject_id,
                Exam.assessment_component_id == assessment_component_id,
            )
            .order_by(Exam.revision_number.desc(), Exam.created_at.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=Exam)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_latest_child_revision(
        db: AsyncSession,
        exam_id: UUID,
        *,
        lock: bool = False,
    ) -> Exam | None:
        query = (
            select(Exam)
            .where(Exam.revision_of_exam_id == exam_id)
            .order_by(Exam.revision_number.desc(), Exam.created_at.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=Exam)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_exam_revisions(
        db: AsyncSession,
        *,
        term_id: UUID,
        curriculum_subject_id: UUID,
        assessment_component_id: UUID,
        title: str | None = None,
    ) -> list[Exam]:
        result = await db.execute(
            select(Exam)
            .where(
                Exam.term_id == term_id,
                Exam.curriculum_subject_id == curriculum_subject_id,
                Exam.assessment_component_id == assessment_component_id,
            )
            .order_by(Exam.revision_number.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    def _apply_exam_filters(
        query,
        *,
        session_id: UUID | None,
        term_id: UUID | None,
        curriculum_subject_id: UUID | None,
        level_id: UUID | None,
        subject_id: UUID | None,
        target_class_id: UUID | None,
        assessment_scheme_id: UUID | None,
        assessment_component_id: UUID | None,
        created_by_actor_id: UUID | None,
        invigilator_teacher_id: UUID | None,
        status: ExamStatus | None,
        roster_status: ExamRosterStatus | None,
    ):
        if level_id is not None or subject_id is not None:
            query = query.join(
                CurriculumSubject,
                CurriculumSubject.id == Exam.curriculum_subject_id,
            )
        if level_id is not None:
            query = query.join(
                Curriculum,
                Curriculum.id == CurriculumSubject.curriculum_id,
            ).where(Curriculum.academic_level_id == level_id)
        if subject_id is not None:
            query = query.where(CurriculumSubject.subject_id == subject_id)
        if target_class_id is not None:
            query = query.join(
                ExamTargetClass,
                ExamTargetClass.exam_id == Exam.id,
            ).where(ExamTargetClass.class_id == target_class_id)
        if invigilator_teacher_id is not None:
            query = query.join(
                ExamInvigilator,
                ExamInvigilator.exam_id == Exam.id,
            ).where(ExamInvigilator.teacher_id == invigilator_teacher_id)
        if session_id is not None:
            query = query.where(Exam.session_id == session_id)
        if term_id is not None:
            query = query.where(Exam.term_id == term_id)
        if curriculum_subject_id is not None:
            query = query.where(Exam.curriculum_subject_id == curriculum_subject_id)
        if assessment_scheme_id is not None:
            query = query.where(Exam.assessment_scheme_id == assessment_scheme_id)
        if assessment_component_id is not None:
            query = query.where(Exam.assessment_component_id == assessment_component_id)
        if created_by_actor_id is not None:
            query = query.where(Exam.created_by_actor_id == created_by_actor_id)
        if status is not None:
            query = query.where(Exam.status == status)
        if roster_status is not None:
            query = query.where(Exam.roster_status == roster_status)
        return query

    @classmethod
    async def list_exams(
        cls,
        db: AsyncSession,
        *,
        session_id: UUID | None = None,
        term_id: UUID | None = None,
        curriculum_subject_id: UUID | None = None,
        level_id: UUID | None = None,
        subject_id: UUID | None = None,
        target_class_id: UUID | None = None,
        assessment_scheme_id: UUID | None = None,
        assessment_component_id: UUID | None = None,
        created_by_actor_id: UUID | None = None,
        invigilator_teacher_id: UUID | None = None,
        status: ExamStatus | None = None,
        roster_status: ExamRosterStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Exam]:
        query = cls._apply_exam_filters(
            select(Exam),
            session_id=session_id,
            term_id=term_id,
            curriculum_subject_id=curriculum_subject_id,
            level_id=level_id,
            subject_id=subject_id,
            target_class_id=target_class_id,
            assessment_scheme_id=assessment_scheme_id,
            assessment_component_id=assessment_component_id,
            created_by_actor_id=created_by_actor_id,
            invigilator_teacher_id=invigilator_teacher_id,
            status=status,
            roster_status=roster_status,
        )
        result = await db.execute(
            query.distinct()
            .order_by(Exam.created_at.desc(), Exam.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def count_exams(cls, db: AsyncSession, **filters) -> int:
        query = cls._apply_exam_filters(
            select(func.count(func.distinct(Exam.id))).select_from(Exam),
            session_id=filters.get("session_id"),
            term_id=filters.get("term_id"),
            curriculum_subject_id=filters.get("curriculum_subject_id"),
            level_id=filters.get("level_id"),
            subject_id=filters.get("subject_id"),
            target_class_id=filters.get("target_class_id"),
            assessment_scheme_id=filters.get("assessment_scheme_id"),
            assessment_component_id=filters.get("assessment_component_id"),
            created_by_actor_id=filters.get("created_by_actor_id"),
            invigilator_teacher_id=filters.get("invigilator_teacher_id"),
            status=filters.get("status"),
            roster_status=filters.get("roster_status"),
        )
        return int((await db.execute(query)).scalar_one() or 0)

    @classmethod
    async def list_exams_for_invigilator(
        cls,
        db: AsyncSession,
        teacher_id: UUID,
        **filters,
    ) -> list[Exam]:
        return await cls.list_exams(db, invigilator_teacher_id=teacher_id, **filters)

    @classmethod
    async def list_exams_for_class(
        cls,
        db: AsyncSession,
        class_id: UUID,
        **filters,
    ) -> list[Exam]:
        return await cls.list_exams(db, target_class_id=class_id, **filters)

    @staticmethod
    async def add_question_selection(
        db: AsyncSession,
        selection: ExamQuestionSelection,
    ) -> ExamQuestionSelection:
        db.add(selection)
        await db.flush()
        return selection

    @staticmethod
    async def add_question_selections(
        db: AsyncSession,
        selections: Sequence[ExamQuestionSelection],
    ) -> list[ExamQuestionSelection]:
        rows = list(selections)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_question_selection(
        db: AsyncSession,
        *,
        exam_id: UUID,
        question_id: UUID,
        lock: bool = False,
    ) -> ExamQuestionSelection | None:
        query = select(ExamQuestionSelection).where(
            ExamQuestionSelection.exam_id == exam_id,
            ExamQuestionSelection.question_id == question_id,
        )
        if lock:
            query = query.with_for_update(of=ExamQuestionSelection)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_question_selections(
        db: AsyncSession,
        exam_id: UUID,
    ) -> list[ExamQuestionSelection]:
        result = await db.execute(
            select(ExamQuestionSelection)
            .where(ExamQuestionSelection.exam_id == exam_id)
            .order_by(
                ExamQuestionSelection.position.asc(),
                ExamQuestionSelection.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_question_selections(db: AsyncSession, exam_id: UUID) -> int:
        value = await db.scalar(
            select(func.count())
            .select_from(ExamQuestionSelection)
            .where(ExamQuestionSelection.exam_id == exam_id)
        )
        return int(value or 0)

    @staticmethod
    async def remove_question_selection(
        db: AsyncSession,
        selection: ExamQuestionSelection,
    ) -> None:
        await db.delete(selection)
        await db.flush()

    @staticmethod
    async def clear_question_selections(db: AsyncSession, exam_id: UUID) -> None:
        await db.execute(
            delete(ExamQuestionSelection).where(
                ExamQuestionSelection.exam_id == exam_id
            )
        )
        await db.flush()

    @staticmethod
    async def list_referenced_question_ids(
        db: AsyncSession,
        question_ids: Sequence[UUID],
    ) -> set[UUID]:
        if not question_ids:
            return set()
        query = (
            select(ExamQuestion.source_question_id)
            .where(ExamQuestion.source_question_id.in_(question_ids))
            .union(
                select(ExamQuestionSelection.question_id).where(
                    ExamQuestionSelection.question_id.in_(question_ids)
                )
            )
        )
        return set((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_referenced_bank_ids(
        db: AsyncSession,
        bank_ids: Sequence[UUID],
    ) -> set[UUID]:
        if not bank_ids:
            return set()
        query = (
            select(Exam.question_bank_id)
            .where(Exam.question_bank_id.in_(bank_ids))
            .distinct()
        )
        return set((await db.execute(query)).scalars().all())

    @staticmethod
    async def is_source_question_referenced(
        db: AsyncSession,
        question_id: UUID,
    ) -> bool:
        frozen_reference = exists().where(
            ExamQuestion.source_question_id == question_id
        )
        draft_reference = exists().where(
            ExamQuestionSelection.question_id == question_id
        )
        value = await db.scalar(select(or_(frozen_reference, draft_reference)))
        return bool(value)

    @staticmethod
    async def add_target_class(
        db: AsyncSession,
        target_class: ExamTargetClass,
    ) -> ExamTargetClass:
        db.add(target_class)
        await db.flush()
        return target_class

    @staticmethod
    async def add_target_classes(
        db: AsyncSession,
        target_classes: Sequence[ExamTargetClass],
    ) -> list[ExamTargetClass]:
        rows = list(target_classes)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_target_class(
        db: AsyncSession,
        exam_id: UUID,
        class_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamTargetClass | None:
        query = select(ExamTargetClass).where(
            ExamTargetClass.exam_id == exam_id,
            ExamTargetClass.class_id == class_id,
        )
        if lock:
            query = query.with_for_update(of=ExamTargetClass)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_target_classes_for_exam(
        db: AsyncSession,
        exam_id: UUID,
    ) -> list[ExamTargetClass]:
        result = await db.execute(
            select(ExamTargetClass)
            .where(ExamTargetClass.exam_id == exam_id)
            .order_by(ExamTargetClass.class_id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def clear_target_classes(db: AsyncSession, exam_id: UUID) -> None:
        await db.execute(
            delete(ExamTargetClass).where(ExamTargetClass.exam_id == exam_id)
        )
        await db.flush()

    @staticmethod
    async def add_invigilator(
        db: AsyncSession,
        invigilator: ExamInvigilator,
    ) -> ExamInvigilator:
        db.add(invigilator)
        await db.flush()
        return invigilator

    @staticmethod
    async def add_invigilators(
        db: AsyncSession,
        invigilators: Sequence[ExamInvigilator],
    ) -> list[ExamInvigilator]:
        rows = list(invigilators)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_invigilator(
        db: AsyncSession,
        exam_id: UUID,
        teacher_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamInvigilator | None:
        query = select(ExamInvigilator).where(
            ExamInvigilator.exam_id == exam_id,
            ExamInvigilator.teacher_id == teacher_id,
        )
        if lock:
            query = query.with_for_update(of=ExamInvigilator)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_invigilators_for_exam(
        db: AsyncSession,
        exam_id: UUID,
    ) -> list[ExamInvigilator]:
        result = await db.execute(
            select(ExamInvigilator)
            .where(ExamInvigilator.exam_id == exam_id)
            .order_by(ExamInvigilator.teacher_id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_invigilators_for_exam_and_teachers(
        db: AsyncSession,
        *,
        exam_id: UUID,
        teacher_ids: Sequence[UUID],
        lock: bool = False,
    ) -> list[ExamInvigilator]:
        unique_ids = list(dict.fromkeys(teacher_ids))
        if not unique_ids:
            return []
        query = select(ExamInvigilator).where(
            ExamInvigilator.exam_id == exam_id,
            ExamInvigilator.teacher_id.in_(unique_ids),
        )
        if lock:
            query = query.with_for_update(of=ExamInvigilator)
        result = await db.execute(query.order_by(ExamInvigilator.teacher_id.asc()))
        return list(result.scalars().all())

    @staticmethod
    async def remove_invigilator(
        db: AsyncSession,
        invigilator: ExamInvigilator,
    ) -> None:
        await db.delete(invigilator)
        await db.flush()

    @staticmethod
    async def clear_invigilators(db: AsyncSession, exam_id: UUID) -> None:
        await db.execute(
            delete(ExamInvigilator).where(ExamInvigilator.exam_id == exam_id)
        )
        await db.flush()

    @staticmethod
    async def remove_invigilators_by_teacher_ids(
        db: AsyncSession,
        *,
        exam_id: UUID,
        teacher_ids: Sequence[UUID],
    ) -> None:
        unique_ids = list(dict.fromkeys(teacher_ids))
        if not unique_ids:
            return
        await db.execute(
            delete(ExamInvigilator).where(
                ExamInvigilator.exam_id == exam_id,
                ExamInvigilator.teacher_id.in_(unique_ids),
            )
        )
        await db.flush()

    @staticmethod
    async def add_suspension(
        db: AsyncSession,
        suspension: ExamSuspension,
    ) -> ExamSuspension:
        db.add(suspension)
        await db.flush()
        return suspension

    @staticmethod
    async def get_suspension_by_id(
        db: AsyncSession,
        suspension_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamSuspension | None:
        query = select(ExamSuspension).where(ExamSuspension.id == suspension_id)
        if lock:
            query = query.with_for_update(of=ExamSuspension)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_open_suspension_for_exam(
        db: AsyncSession,
        exam_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamSuspension | None:
        query = (
            select(ExamSuspension)
            .where(
                ExamSuspension.exam_id == exam_id,
                ExamSuspension.resumed_at.is_(None),
            )
            .order_by(ExamSuspension.suspended_at.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=ExamSuspension)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_suspensions_for_exam(
        db: AsyncSession,
        exam_id: UUID,
    ) -> list[ExamSuspension]:
        result = await db.execute(
            select(ExamSuspension)
            .where(ExamSuspension.exam_id == exam_id)
            .order_by(ExamSuspension.suspended_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def save_suspension(
        db: AsyncSession,
        suspension: ExamSuspension,
    ) -> ExamSuspension:
        db.add(suspension)
        await db.flush()
        return suspension

    @staticmethod
    async def add_exam_question(
        db: AsyncSession,
        question: ExamQuestion,
    ) -> ExamQuestion:
        db.add(question)
        await db.flush()
        return question

    @staticmethod
    async def add_exam_questions(
        db: AsyncSession,
        questions: Sequence[ExamQuestion],
    ) -> list[ExamQuestion]:
        rows = list(questions)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_exam_question_by_id(
        db: AsyncSession,
        question_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamQuestion | None:
        query = select(ExamQuestion).where(ExamQuestion.id == question_id)
        if lock:
            query = query.with_for_update(of=ExamQuestion)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_exam_question_for_source(
        db: AsyncSession,
        exam_id: UUID,
        source_question_id: UUID,
    ) -> ExamQuestion | None:
        return (
            await db.execute(
                select(ExamQuestion).where(
                    ExamQuestion.exam_id == exam_id,
                    ExamQuestion.source_question_id == source_question_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_exam_questions(
        db: AsyncSession,
        exam_id: UUID,
    ) -> list[ExamQuestion]:
        result = await db.execute(
            select(ExamQuestion)
            .where(ExamQuestion.exam_id == exam_id)
            .order_by(ExamQuestion.position.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_exam_questions(db: AsyncSession, exam_id: UUID) -> int:
        value = await db.scalar(
            select(func.count())
            .select_from(ExamQuestion)
            .where(ExamQuestion.exam_id == exam_id)
        )
        return int(value or 0)

    @staticmethod
    async def add_exam_question_option(
        db: AsyncSession,
        option: ExamQuestionOption,
    ) -> ExamQuestionOption:
        db.add(option)
        await db.flush()
        return option

    @staticmethod
    async def add_exam_question_options(
        db: AsyncSession,
        options: Sequence[ExamQuestionOption],
    ) -> list[ExamQuestionOption]:
        rows = list(options)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def list_exam_question_options(
        db: AsyncSession,
        exam_question_id: UUID,
    ) -> list[ExamQuestionOption]:
        result = await db.execute(
            select(ExamQuestionOption)
            .where(ExamQuestionOption.exam_question_id == exam_question_id)
            .order_by(ExamQuestionOption.position.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_exam_question_options_for_exam(
        db: AsyncSession,
        exam_id: UUID,
    ) -> list[ExamQuestionOption]:
        result = await db.execute(
            select(ExamQuestionOption)
            .join(
                ExamQuestion,
                ExamQuestion.id == ExamQuestionOption.exam_question_id,
            )
            .where(ExamQuestion.exam_id == exam_id)
            .order_by(
                ExamQuestion.position.asc(),
                ExamQuestionOption.position.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def has_unfinished_scheduled_exam_for_level(
        db: AsyncSession,
        *,
        session_id: UUID,
        term_id: UUID,
        level_id: UUID,
    ) -> bool:
        child_exam = aliased(Exam)
        has_newer_revision = (
            select(child_exam.id)
            .where(child_exam.revision_of_exam_id == Exam.id)
            .exists()
        )

        unfinished_exam_exists = (
            select(Exam.id)
            .join(
                CurriculumSubject,
                CurriculumSubject.id == Exam.curriculum_subject_id,
            )
            .join(
                Curriculum,
                Curriculum.id == CurriculumSubject.curriculum_id,
            )
            .where(
                Exam.session_id == session_id,
                Exam.term_id == term_id,
                Curriculum.academic_level_id == level_id,
                Exam.scheduled_start_at.is_not(None),
                Exam.status.notin_((ExamStatus.CLOSED, ExamStatus.CANCELLED)),
                ~has_newer_revision,
            )
            .exists()
        )

        return bool(await db.scalar(select(unfinished_exam_exists)))
