from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.academics.repository import AcademicRepository
from app.domains.exams.repository import ExamRepository
from app.domains.questions.models import (
    Question,
    QuestionBank,
    QuestionType,
)
from app.domains.questions.repository import QuestionRepository
from app.domains.questions.response_builder import (
    build_question_bank_responses,
    build_question_response,
    build_question_responses,
)
from app.domains.questions.service import QuestionService


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


def _question(*, author_id):
    return Question(
        id=uuid4(),
        bank_id=uuid4(),
        question_type=QuestionType.SINGLE_CHOICE,
        prompt="Question",
        instruction=None,
        image_asset_id=None,
        version=1,
        created_by_actor_id=author_id,
        last_edited_by_actor_id=None,
        is_active=True,
    )


class QuestionAuthorResponseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        for repository, method in [
            (ExamRepository, "list_referenced_question_ids"),
            (ExamRepository, "list_referenced_bank_ids"),
            (QuestionRepository, "list_nonempty_bank_ids"),
        ]:
            patcher = patch.object(
                repository, method, new=AsyncMock(return_value=set())
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_delete_bank_rechecks_exam_references_before_mutation(self):
        actor = SimpleNamespace(id=uuid4(), role="admin", is_active=True)
        bank = SimpleNamespace(id=uuid4())
        db = SimpleNamespace(commit=AsyncMock())
        ExamRepository.list_referenced_bank_ids.return_value = {bank.id}
        with (
            patch.object(
                QuestionRepository, "get_bank_by_id", new=AsyncMock(return_value=bank)
            ),
            patch.object(
                QuestionRepository,
                "count_questions_for_bank",
                new=AsyncMock(return_value=0),
            ),
            patch.object(QuestionRepository, "delete_bank", new=AsyncMock()) as delete,
            self.assertRaisesRegex(ValueError, "used by an exam"),
        ):
            await QuestionService.delete_empty_question_bank(
                db, actor=actor, bank_id=bank.id
            )
        delete.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_delete_eligibility_respects_authorship_and_exam_references(self):
        teacher = SimpleNamespace(id=uuid4(), role="teacher")
        own = _question(author_id=teacher.id)
        used = _question(author_id=teacher.id)
        other = _question(author_id=uuid4())
        questions = [own, used, other]
        ExamRepository.list_referenced_question_ids.return_value = {used.id}
        with (
            patch.object(
                QuestionRepository,
                "list_options_for_questions",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.domains.questions.response_builder._load_author_names",
                new=AsyncMock(return_value={}),
            ),
        ):
            responses = await build_question_responses(
                object(), questions, request_actor=teacher
            )
            self.assertEqual(
                [row.can_delete for row in responses], [True, False, False]
            )
            admin = SimpleNamespace(id=uuid4(), role="admin")
            responses = await build_question_responses(
                object(), questions, request_actor=admin
            )
            self.assertEqual([row.can_delete for row in responses], [True, False, True])

    async def test_only_empty_unreferenced_banks_are_deletable_by_admin(self):
        actor = SimpleNamespace(id=uuid4(), role="admin")
        banks = [
            QuestionBank(
                id=uuid4(),
                curriculum_subject_id=uuid4(),
                name="Bank",
                description=None,
                created_by_actor_id=actor.id,
                is_active=True,
            )
            for _ in range(3)
        ]
        QuestionRepository.list_nonempty_bank_ids.return_value = {banks[1].id}
        ExamRepository.list_referenced_bank_ids.return_value = {banks[2].id}
        responses = await build_question_bank_responses(
            object(), banks, request_actor=actor
        )
        self.assertEqual([row.can_delete for row in responses], [True, False, False])
        actor.role = "teacher"
        responses = await build_question_bank_responses(
            object(), banks, request_actor=actor
        )
        self.assertEqual([row.can_delete for row in responses], [False, False, False])

    async def test_teacher_question_prefers_current_academic_name(self) -> None:
        membership_id = uuid4()
        teacher = SimpleNamespace(
            id=uuid4(),
            role="teacher",
            display_name="Ada Old Name",
            weave_membership_id=str(membership_id),
        )
        current_teacher = SimpleNamespace(
            id=membership_id,
            first_name="Ada",
            last_name="Okafor",
        )
        question = _question(author_id=teacher.id)
        db = object()

        with (
            patch.object(
                QuestionRepository,
                "list_options_for_question",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                AcademicRepository,
                "list_teachers_by_ids",
                new=AsyncMock(return_value=[current_teacher]),
            ) as list_teachers,
        ):
            response = await build_question_response(
                db,
                question,
                request_actor=teacher,
            )

        self.assertEqual(response.author_name, "Ada Okafor")
        self.assertEqual(response.created_by_actor_id, teacher.id)
        list_teachers.assert_awaited_once_with(
            db,
            [membership_id],
            active_only=False,
        )

    async def test_teacher_question_falls_back_to_local_display_name(self) -> None:
        membership_id = uuid4()
        teacher = SimpleNamespace(
            id=uuid4(),
            role="teacher",
            display_name="Former Teacher Name",
            weave_membership_id=str(membership_id),
        )
        question = _question(author_id=teacher.id)
        db = object()

        with (
            patch.object(
                QuestionRepository,
                "list_options_for_question",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                AcademicRepository,
                "list_teachers_by_ids",
                new=AsyncMock(return_value=[]),
            ),
        ):
            response = await build_question_response(
                db,
                question,
                request_actor=teacher,
            )

        self.assertEqual(response.author_name, "Former Teacher Name")

    async def test_admin_question_is_labeled_admin_not_personal_name(self) -> None:
        admin = SimpleNamespace(
            id=uuid4(),
            role="admin",
            display_name="Jane Administrator",
            weave_membership_id=None,
        )
        question = _question(author_id=admin.id)

        with patch.object(
            QuestionRepository,
            "list_options_for_question",
            new=AsyncMock(return_value=[]),
        ):
            response = await build_question_response(
                object(),
                question,
                request_actor=admin,
            )

        self.assertEqual(response.author_name, "Admin")

    async def test_bulk_questions_batch_actor_and_teacher_resolution(self) -> None:
        membership_id = uuid4()
        teacher = SimpleNamespace(
            id=uuid4(),
            role="teacher",
            display_name="Old Chidi Name",
            weave_membership_id=str(membership_id),
        )
        current_teacher = SimpleNamespace(
            id=membership_id,
            first_name="Chidi",
            last_name="Bello",
        )
        admin = SimpleNamespace(
            id=uuid4(),
            role="admin",
            display_name="Named Admin",
            weave_membership_id=None,
        )
        questions = [
            _question(author_id=teacher.id),
            _question(author_id=teacher.id),
            _question(author_id=admin.id),
        ]
        db = SimpleNamespace(
            execute=AsyncMock(return_value=_ScalarRows([teacher, admin]))
        )

        with (
            patch.object(
                QuestionRepository,
                "list_options_for_questions",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                AcademicRepository,
                "list_teachers_by_ids",
                new=AsyncMock(return_value=[current_teacher]),
            ) as list_teachers,
        ):
            responses = await build_question_responses(db, questions)

        self.assertEqual(
            [response.author_name for response in responses],
            ["Chidi Bello", "Chidi Bello", "Admin"],
        )
        db.execute.assert_awaited_once()
        list_teachers.assert_awaited_once_with(
            db,
            [membership_id],
            active_only=False,
        )


if __name__ == "__main__":
    unittest.main()
