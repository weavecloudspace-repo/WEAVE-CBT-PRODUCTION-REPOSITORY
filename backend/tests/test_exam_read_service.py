from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DEBUG"] = "false"

from app.core.exceptions import AcademicAuthorizationError
from app.domains.academics.authorization import (
    AcademicAuthorizationService,
)
from app.domains.exams.exceptions import (
    ExamAuthorizationError,
    ExamNotFound,
)
from app.domains.exams.repository import ExamRepository
from app.domains.exams.service import ExamService


def actor(*, role: str = "teacher", membership_id: UUID | None = None):
    return SimpleNamespace(
        id=uuid4(),
        role=role,
        is_active=True,
        weave_membership_id=(
            str(membership_id or uuid4()) if role == "teacher" else None
        ),
    )


def exam(**overrides):
    values = {
        "id": uuid4(),
        "term_id": uuid4(),
        "curriculum_subject_id": uuid4(),
        "created_by_actor_id": uuid4(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ExamReadServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_can_get_exam(self) -> None:
        db = AsyncMock()
        current_exam = exam()
        with patch.object(
            ExamRepository,
            "get_exam_by_id",
            new=AsyncMock(return_value=current_exam),
        ):
            result = await ExamService.get_exam(
                db,
                actor=actor(role="admin"),
                exam_id=current_exam.id,
            )
        self.assertIs(result, current_exam)

    async def test_assigned_invigilator_can_get_exam_without_authoring_access(
        self,
    ) -> None:
        db = AsyncMock()
        teacher_id = uuid4()
        current_actor = actor(role="teacher", membership_id=teacher_id)
        current_exam = exam()
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_invigilator",
                new=AsyncMock(return_value=SimpleNamespace()),
            ) as get_invigilator,
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject_for_term",
                new=AsyncMock(),
            ) as require_authoring,
        ):
            result = await ExamService.get_exam(
                db,
                actor=current_actor,
                exam_id=current_exam.id,
            )

        self.assertIs(result, current_exam)
        get_invigilator.assert_awaited_once_with(db, current_exam.id, teacher_id)
        require_authoring.assert_not_awaited()

    async def test_second_eligible_teacher_can_get_shared_exam(self) -> None:
        db = AsyncMock()
        current_actor = actor(role="teacher")
        current_exam = exam()
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_invigilator",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject_for_term",
                new=AsyncMock(),
            ) as require_authoring,
        ):
            result = await ExamService.get_exam(
                db,
                actor=current_actor,
                exam_id=current_exam.id,
            )

        self.assertIs(result, current_exam)
        require_authoring.assert_awaited_once_with(
            db,
            actor=current_actor,
            curriculum_subject_id=current_exam.curriculum_subject_id,
            academic_term_id=current_exam.term_id,
        )

    async def test_lead_must_still_have_current_term_authoring_scope(self) -> None:
        db = AsyncMock()
        current_actor = actor(role="teacher")
        current_exam = exam(created_by_actor_id=current_actor.id)
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject_for_term",
                new=AsyncMock(side_effect=AcademicAuthorizationError("No assignment")),
            ),
            self.assertRaisesRegex(ExamAuthorizationError, "not allowed"),
        ):
            await ExamService.get_exam(
                db,
                actor=current_actor,
                exam_id=current_exam.id,
            )

    async def test_unrelated_teacher_cannot_get_exam(self) -> None:
        db = AsyncMock()
        current_actor = actor(role="teacher")
        current_exam = exam()
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_invigilator",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject_for_term",
                new=AsyncMock(side_effect=AcademicAuthorizationError("No assignment")),
            ),
            self.assertRaisesRegex(ExamAuthorizationError, "not allowed"),
        ):
            await ExamService.get_exam(
                db,
                actor=current_actor,
                exam_id=current_exam.id,
            )

    async def test_missing_exam_raises_not_found(self) -> None:
        db = AsyncMock()
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=None),
            ),
            self.assertRaises(ExamNotFound),
        ):
            await ExamService.get_exam(
                db,
                actor=actor(role="admin"),
                exam_id=uuid4(),
            )


if __name__ == "__main__":
    unittest.main()
