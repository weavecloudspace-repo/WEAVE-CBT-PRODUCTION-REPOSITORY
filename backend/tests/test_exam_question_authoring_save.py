from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.academics.authorization import (
    AcademicAuthorizationService,
)
from app.domains.exams.models import ExamQuestionSelectionMode, ExamStatus
from app.domains.exams.question_authoring_schema import (
    ExamQuestionAuthoringSave,
)
from app.domains.exams.repository import ExamRepository
from app.domains.exams.service import ExamService
from app.domains.questions.repository import QuestionRepository


def make_exam(*, bank_id, count=3, version=7):
    return SimpleNamespace(
        id=uuid4(),
        status=ExamStatus.DRAFT,
        authoring_version=version,
        curriculum_subject_id=uuid4(),
        term_id=uuid4(),
        question_bank_id=bank_id,
        question_selection_mode=ExamQuestionSelectionMode.MANUAL,
        question_count=count,
    )


def selection(exam_id, question_id, actor_id, position):
    return SimpleNamespace(
        exam_id=exam_id,
        question_id=question_id,
        added_by_actor_id=actor_id,
        position=position,
    )


async def save_with_mocks(*, exam, payload, existing, questions, bank):
    actor = SimpleNamespace(id=uuid4(), role="admin", is_active=True)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch.object(
            ExamRepository, "get_exam_by_id", new=AsyncMock(return_value=exam)
        ),
        patch.object(
            ExamRepository,
            "list_question_selections",
            new=AsyncMock(return_value=existing),
        ),
        patch.object(
            ExamRepository, "clear_question_selections", new=AsyncMock()
        ) as clear,
        patch.object(ExamRepository, "add_question_selections", new=AsyncMock()) as add,
        patch.object(
            ExamRepository, "save_exam", new=AsyncMock(side_effect=lambda _db, row: row)
        ),
        patch.object(
            QuestionRepository, "get_bank_by_id", new=AsyncMock(return_value=bank)
        ),
        patch.object(
            QuestionRepository,
            "list_questions_by_ids",
            new=AsyncMock(return_value=questions),
        ),
        patch.object(
            AcademicAuthorizationService,
            "require_can_author_curriculum_subject_for_term",
            new=AsyncMock(),
        ),
    ):
        result = await ExamService.save_question_authoring(
            db,
            actor=actor,
            exam_id=exam.id,
            payload=payload,
        )

    return result, actor, db, clear, add


@pytest.mark.asyncio
async def test_increasing_count_and_adding_questions_commit_as_one_authoring_save() -> (
    None
):
    bank_id = uuid4()
    exam = make_exam(bank_id=bank_id)
    original_author = uuid4()
    question_ids = [uuid4() for _ in range(5)]
    existing = [
        selection(exam.id, question_id, original_author, position)
        for position, question_id in enumerate(question_ids[:3], start=1)
    ]
    questions = [
        SimpleNamespace(id=question_id, bank_id=bank_id, is_active=True)
        for question_id in question_ids
    ]
    bank = SimpleNamespace(
        id=bank_id,
        curriculum_subject_id=exam.curriculum_subject_id,
        is_active=True,
    )
    payload = ExamQuestionAuthoringSave(
        question_bank_id=bank_id,
        question_selection_mode="manual",
        question_count=5,
        manual_question_ids=question_ids,
        expected_authoring_version=7,
    )

    result, actor, db, clear, add = await save_with_mocks(
        exam=exam,
        payload=payload,
        existing=existing,
        questions=questions,
        bank=bank,
    )

    assert result.question_count == 5
    assert result.authoring_version == 8
    clear.assert_awaited_once_with(db, exam.id)
    add.assert_awaited_once()
    rows = add.await_args.args[1]
    assert [row.question_id for row in rows] == question_ids
    assert [row.position for row in rows] == [1, 2, 3, 4, 5]
    assert [row.added_by_actor_id for row in rows[:3]] == [original_author] * 3
    assert [row.added_by_actor_id for row in rows[3:]] == [actor.id, actor.id]
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_decreasing_count_can_remove_questions_in_the_same_save() -> None:
    bank_id = uuid4()
    exam = make_exam(bank_id=bank_id, count=5)
    actor_id = uuid4()
    question_ids = [uuid4() for _ in range(5)]
    existing = [
        selection(exam.id, question_id, actor_id, position)
        for position, question_id in enumerate(question_ids, start=1)
    ]
    kept_ids = question_ids[:3]
    questions = [
        SimpleNamespace(id=question_id, bank_id=bank_id, is_active=True)
        for question_id in kept_ids
    ]
    bank = SimpleNamespace(
        id=bank_id,
        curriculum_subject_id=exam.curriculum_subject_id,
        is_active=True,
    )
    payload = ExamQuestionAuthoringSave(
        question_bank_id=bank_id,
        question_selection_mode="manual",
        question_count=3,
        manual_question_ids=kept_ids,
        expected_authoring_version=7,
    )

    result, _actor, db, _clear, add = await save_with_mocks(
        exam=exam,
        payload=payload,
        existing=existing,
        questions=questions,
        bank=bank,
    )

    assert result.question_count == 3
    rows = add.await_args.args[1]
    assert [row.question_id for row in rows] == kept_ids
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_switching_manual_bank_replaces_old_selection_with_new_bank_questions() -> (
    None
):
    old_bank_id = uuid4()
    new_bank_id = uuid4()
    exam = make_exam(bank_id=old_bank_id)
    old_ids = [uuid4() for _ in range(3)]
    new_ids = [uuid4() for _ in range(2)]
    existing = [
        selection(exam.id, question_id, uuid4(), position)
        for position, question_id in enumerate(old_ids, start=1)
    ]
    questions = [
        SimpleNamespace(id=question_id, bank_id=new_bank_id, is_active=True)
        for question_id in new_ids
    ]
    bank = SimpleNamespace(
        id=new_bank_id,
        curriculum_subject_id=exam.curriculum_subject_id,
        is_active=True,
    )
    payload = ExamQuestionAuthoringSave(
        question_bank_id=new_bank_id,
        question_selection_mode="manual",
        question_count=4,
        manual_question_ids=new_ids,
        expected_authoring_version=7,
    )

    result, _actor, db, clear, add = await save_with_mocks(
        exam=exam,
        payload=payload,
        existing=existing,
        questions=questions,
        bank=bank,
    )

    assert result.question_bank_id == new_bank_id
    assert result.question_count == 4
    clear.assert_awaited_once()
    assert [row.question_id for row in add.await_args.args[1]] == new_ids
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_archived_existing_question_may_remain_but_archived_question_cannot_be_newly_added() -> (
    None
):
    bank_id = uuid4()
    exam = make_exam(bank_id=bank_id, count=2)
    existing_id = uuid4()
    archived_new_id = uuid4()
    existing = [selection(exam.id, existing_id, uuid4(), 1)]
    bank = SimpleNamespace(
        id=bank_id,
        curriculum_subject_id=exam.curriculum_subject_id,
        is_active=True,
    )

    keep_payload = ExamQuestionAuthoringSave(
        question_bank_id=bank_id,
        question_selection_mode="manual",
        question_count=2,
        manual_question_ids=[existing_id],
        expected_authoring_version=7,
    )
    kept_question = SimpleNamespace(id=existing_id, bank_id=bank_id, is_active=False)
    result, _actor, db, _clear, _add = await save_with_mocks(
        exam=exam,
        payload=keep_payload,
        existing=existing,
        questions=[kept_question],
        bank=bank,
    )
    assert result.authoring_version == 7
    db.commit.assert_awaited_once()

    add_payload = ExamQuestionAuthoringSave(
        question_bank_id=bank_id,
        question_selection_mode="manual",
        question_count=2,
        manual_question_ids=[existing_id, archived_new_id],
        expected_authoring_version=7,
    )
    with pytest.raises(ValueError, match="Archived questions cannot be newly added"):
        await save_with_mocks(
            exam=exam,
            payload=add_payload,
            existing=existing,
            questions=[
                kept_question,
                SimpleNamespace(id=archived_new_id, bank_id=bank_id, is_active=False),
            ],
            bank=bank,
        )
