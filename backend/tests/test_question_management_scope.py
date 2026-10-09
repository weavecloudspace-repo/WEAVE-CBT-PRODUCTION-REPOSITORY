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

from app.domains.questions.repository import QuestionRepository
from app.domains.questions.service import QuestionService


class QuestionManagementScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_teacher_management_scope_is_limited_to_own_questions(self) -> None:
        actor = SimpleNamespace(
            id=uuid4(),
            role="teacher",
            is_active=True,
            weave_membership_id=str(uuid4()),
        )
        bank = SimpleNamespace(id=uuid4())
        expected = [SimpleNamespace(id=uuid4(), created_by_actor_id=actor.id)]
        db = object()

        with (
            patch.object(
                QuestionService,
                "list_actor_authorable_question_banks",
                new=AsyncMock(return_value=[bank]),
            ),
            patch.object(
                QuestionRepository,
                "list_questions_for_banks",
                new=AsyncMock(return_value=expected),
            ) as list_questions,
        ):
            result = await QuestionService.list_actor_manageable_questions(
                db,
                actor=actor,
                active_only=False,
            )

        self.assertEqual(result, expected)
        list_questions.assert_awaited_once_with(
            db,
            [bank.id],
            created_by_actor_id=actor.id,
            active_only=False,
            offset=0,
            limit=None,
        )

    async def test_admin_management_scope_is_not_filtered_by_creator(self) -> None:
        actor = SimpleNamespace(
            id=uuid4(),
            role="admin",
            is_active=True,
            weave_membership_id=None,
        )
        banks = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
        expected = [
            SimpleNamespace(id=uuid4(), created_by_actor_id=uuid4()),
            SimpleNamespace(id=uuid4(), created_by_actor_id=actor.id),
        ]
        db = object()

        with (
            patch.object(
                QuestionRepository,
                "list_banks",
                new=AsyncMock(return_value=banks),
            ) as list_banks,
            patch.object(
                QuestionRepository,
                "list_questions_for_banks",
                new=AsyncMock(return_value=expected),
            ) as list_questions,
        ):
            result = await QuestionService.list_actor_manageable_questions(
                db,
                actor=actor,
                active_only=False,
            )

        self.assertEqual(result, expected)
        list_banks.assert_awaited_once_with(db, active_only=False)
        list_questions.assert_awaited_once()
        args, kwargs = list_questions.await_args
        self.assertIs(args[0], db)
        self.assertEqual(set(args[1]), {bank.id for bank in banks})
        self.assertIsNone(kwargs["created_by_actor_id"])
        self.assertFalse(kwargs["active_only"])
        self.assertEqual(kwargs["offset"], 0)
        self.assertIsNone(kwargs["limit"])

    async def test_teacher_cannot_request_management_scope_for_unauthorized_bank(
        self,
    ) -> None:
        actor = SimpleNamespace(
            id=uuid4(),
            role="teacher",
            is_active=True,
            weave_membership_id=str(uuid4()),
        )
        allowed_bank = SimpleNamespace(id=uuid4())
        requested_bank_id = uuid4()
        db = object()

        with (
            patch.object(
                QuestionService,
                "list_actor_authorable_question_banks",
                new=AsyncMock(return_value=[allowed_bank]),
            ),
            self.assertRaisesRegex(
                Exception,
                "not allowed to manage questions in this bank",
            ),
        ):
            await QuestionService.list_actor_manageable_questions(
                db,
                actor=actor,
                bank_id=requested_bank_id,
            )
