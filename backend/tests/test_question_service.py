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

from app.core.exceptions import AcademicAuthorizationError
from app.domains.academics.authorization import (
    AcademicAuthorizationService,
)
from app.domains.exams.repository import ExamRepository
from app.domains.media.service import MediaService
from app.domains.questions.models import (
    Question,
    QuestionBank,
    QuestionType,
)
from app.domains.questions.repository import QuestionRepository
from app.domains.questions.schemas import (
    QuestionBankUpdate,
    QuestionOptionCreate,
    QuestionUpdate,
    SingleChoiceQuestionCreate,
)
from app.domains.questions.service import (
    QuestionService,
    _normalize_and_validate_options,
    _require_can_manage_question,
)


def actor(*, role: str = "teacher") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        role=role,
        is_active=True,
        weave_membership_id=str(uuid4()) if role == "teacher" else None,
    )


def bank(*, active: bool = True) -> QuestionBank:
    return QuestionBank(
        id=uuid4(),
        curriculum_subject_id=uuid4(),
        name="MATHEMATICS",
        description=None,
        created_by_actor_id=uuid4(),
        is_active=active,
    )


def question(
    *,
    owner_id,
    bank_id,
    image_asset_id=None,
    active: bool = True,
) -> Question:
    return Question(
        id=uuid4(),
        bank_id=bank_id,
        question_type=QuestionType.SINGLE_CHOICE,
        prompt="Original prompt",
        instruction=None,
        image_asset_id=image_asset_id,
        version=1,
        created_by_actor_id=owner_id,
        last_edited_by_actor_id=None,
        is_active=active,
    )


class QuestionValidationTests(unittest.TestCase):
    def test_multiple_choice_requires_two_correct_and_one_incorrect(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two correct"):
            _normalize_and_validate_options(
                [
                    QuestionOptionCreate(text="A", is_correct=True),
                    QuestionOptionCreate(text="B", is_correct=False),
                ],
                question_type=QuestionType.MULTIPLE_CHOICE,
            )

        with self.assertRaisesRegex(ValueError, "at least one incorrect"):
            _normalize_and_validate_options(
                [
                    QuestionOptionCreate(text="A", is_correct=True),
                    QuestionOptionCreate(text="B", is_correct=True),
                ],
                question_type=QuestionType.MULTIPLE_CHOICE,
            )

        normalized = _normalize_and_validate_options(
            [
                QuestionOptionCreate(text=" A ", is_correct=True),
                QuestionOptionCreate(text="B", is_correct=True),
                QuestionOptionCreate(text="C", is_correct=False),
            ],
            question_type=QuestionType.MULTIPLE_CHOICE,
        )
        self.assertEqual(
            normalized,
            [("A", None, True), ("B", None, True), ("C", None, False)],
        )

    def test_duplicate_option_text_is_case_insensitive(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be unique"):
            _normalize_and_validate_options(
                [
                    QuestionOptionCreate(text="Lagos", is_correct=True),
                    QuestionOptionCreate(text=" lagos ", is_correct=False),
                ],
                question_type=QuestionType.SINGLE_CHOICE,
            )

    def test_teacher_cannot_manage_another_teachers_question(self) -> None:
        current_actor = actor()
        other_question = question(
            owner_id=uuid4(),
            bank_id=uuid4(),
        )

        with self.assertRaises(AcademicAuthorizationError):
            _require_can_manage_question(
                actor=current_actor,  # type: ignore[arg-type]
                question=other_question,
            )


class QuestionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_single_choice_persists_question_options_and_commits(
        self,
    ) -> None:
        db = AsyncMock()
        current_actor = actor()
        current_bank = bank()
        created_question_id = uuid4()

        async def add_question(_db, row):
            row.id = created_question_id
            return row

        with (
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=current_bank),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                QuestionRepository,
                "add_question",
                new=AsyncMock(side_effect=add_question),
            ) as add_question_mock,
            patch.object(
                QuestionRepository,
                "add_options",
                new=AsyncMock(return_value=[]),
            ) as add_options,
        ):
            result = await QuestionService.create_single_choice_question(
                db,
                actor=current_actor,  # type: ignore[arg-type]
                bank_id=current_bank.id,
                payload=SingleChoiceQuestionCreate(
                    prompt="  Capital of Nigeria?  ",
                    options=[
                        QuestionOptionCreate(text="Lagos", is_correct=False),
                        QuestionOptionCreate(text="Abuja", is_correct=True),
                    ],
                ),
            )

        self.assertEqual(result.id, created_question_id)
        self.assertEqual(result.prompt, "Capital of Nigeria?")
        self.assertEqual(result.question_type, QuestionType.SINGLE_CHOICE)
        self.assertEqual(result.version, 1)
        add_question_mock.assert_awaited_once()
        saved_options = add_options.await_args.args[1]
        self.assertEqual([item.position for item in saved_options], [1, 2])
        self.assertEqual([item.text for item in saved_options], ["Lagos", "Abuja"])
        db.commit.assert_awaited_once()

    async def test_update_omitted_image_preserves_asset_and_increments_version(
        self,
    ) -> None:
        db = AsyncMock()
        current_actor = actor()
        current_bank = bank()
        image_id = uuid4()
        current_question = question(
            owner_id=current_actor.id,
            bank_id=current_bank.id,
            image_asset_id=image_id,
        )

        with (
            patch.object(
                QuestionRepository,
                "get_question_by_id",
                new=AsyncMock(return_value=current_question),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=current_bank),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                QuestionRepository,
                "save_question",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
            patch.object(
                MediaService,
                "delete_unreferenced_asset",
                new=AsyncMock(),
            ) as cleanup,
        ):
            result = await QuestionService.update_question(
                db,
                actor=current_actor,  # type: ignore[arg-type]
                question_id=current_question.id,
                payload=QuestionUpdate(prompt="Changed prompt"),
            )

        self.assertEqual(result.image_asset_id, image_id)
        self.assertEqual(result.version, 2)
        self.assertEqual(result.last_edited_by_actor_id, current_actor.id)
        cleanup.assert_not_awaited()
        db.commit.assert_awaited_once()

    async def test_explicit_same_existing_image_does_not_require_editor_ownership(
        self,
    ) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        teacher_owner_id = uuid4()
        current_bank = bank()
        image_id = uuid4()
        current_question = question(
            owner_id=teacher_owner_id,
            bank_id=current_bank.id,
            image_asset_id=image_id,
        )

        with (
            patch.object(
                QuestionRepository,
                "get_question_by_id",
                new=AsyncMock(return_value=current_question),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=current_bank),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                QuestionRepository,
                "save_question",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
            patch(
                "app.domains.questions.service._resolve_new_question_image",
                new=AsyncMock(),
            ) as resolve_new_image,
            patch.object(
                MediaService,
                "delete_unreferenced_asset",
                new=AsyncMock(),
            ) as cleanup,
        ):
            result = await QuestionService.update_question(
                db,
                actor=admin,  # type: ignore[arg-type]
                question_id=current_question.id,
                payload=QuestionUpdate(
                    prompt="Admin edit",
                    image_asset_id=image_id,
                ),
            )

        self.assertEqual(result.image_asset_id, image_id)
        self.assertEqual(result.version, 2)
        resolve_new_image.assert_not_awaited()
        cleanup.assert_not_awaited()

    async def test_update_explicit_null_removes_image_and_cleans_old_asset(
        self,
    ) -> None:
        db = AsyncMock()
        current_actor = actor()
        current_bank = bank()
        image_id = uuid4()
        current_question = question(
            owner_id=current_actor.id,
            bank_id=current_bank.id,
            image_asset_id=image_id,
        )

        with (
            patch.object(
                QuestionRepository,
                "get_question_by_id",
                new=AsyncMock(return_value=current_question),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=current_bank),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                QuestionRepository,
                "save_question",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
            patch.object(
                MediaService,
                "delete_unreferenced_asset",
                new=AsyncMock(return_value=True),
            ) as cleanup,
        ):
            result = await QuestionService.update_question(
                db,
                actor=current_actor,  # type: ignore[arg-type]
                question_id=current_question.id,
                payload=QuestionUpdate(image_asset_id=None),
            )

        self.assertIsNone(result.image_asset_id)
        self.assertEqual(result.version, 2)
        cleanup.assert_awaited_once_with(db, asset_id=image_id)

    async def test_bank_curriculum_cannot_change_while_any_question_row_exists(
        self,
    ) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_bank = bank()

        with (
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=current_bank),
            ),
            patch.object(
                QuestionRepository,
                "count_questions_for_bank",
                new=AsyncMock(return_value=1),
            ),
            self.assertRaisesRegex(ValueError, "only change while the bank is empty"),
        ):
            await QuestionService.update_question_bank(
                db,
                actor=admin,  # type: ignore[arg-type]
                bank_id=current_bank.id,
                payload=QuestionBankUpdate(
                    curriculum_subject_id=uuid4(),
                ),
            )

        db.commit.assert_not_awaited()

    async def test_used_question_cannot_be_hard_deleted(self) -> None:
        db = AsyncMock()
        current_actor = actor()
        current_bank = bank()
        current_question = question(
            owner_id=current_actor.id,
            bank_id=current_bank.id,
        )

        with (
            patch.object(
                QuestionRepository,
                "get_question_by_id",
                new=AsyncMock(return_value=current_question),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=current_bank),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "is_source_question_referenced",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                QuestionRepository,
                "delete_question",
                new=AsyncMock(),
            ) as delete_question,
            self.assertRaisesRegex(ValueError, "cannot be deleted"),
        ):
            await QuestionService.delete_unused_question(
                db,
                actor=current_actor,  # type: ignore[arg-type]
                question_id=current_question.id,
            )

        delete_question.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_archive_does_not_increment_question_version(self) -> None:
        db = AsyncMock()
        current_actor = actor()
        current_bank = bank()
        current_question = question(
            owner_id=current_actor.id,
            bank_id=current_bank.id,
        )

        with (
            patch.object(
                QuestionRepository,
                "get_question_by_id",
                new=AsyncMock(return_value=current_question),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=current_bank),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                QuestionRepository,
                "save_question",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            result = await QuestionService.archive_question(
                db,
                actor=current_actor,  # type: ignore[arg-type]
                question_id=current_question.id,
            )

        self.assertFalse(result.is_active)
        self.assertEqual(result.version, 1)
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
