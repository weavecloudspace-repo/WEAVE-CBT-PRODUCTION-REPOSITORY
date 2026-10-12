from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
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
from app.domains.candidates.models import CandidateStatus
from app.domains.candidates.repository import CandidateRepository
from app.domains.candidates.service import CandidateService
from app.domains.exams.repository import ExamRepository


def actor(*, role: str = "admin", membership_id: UUID | None = None):
    return SimpleNamespace(
        id=uuid4(),
        role=role,
        is_active=True,
        weave_membership_id=(
            str(membership_id or uuid4()) if role == "teacher" else None
        ),
    )


def candidate(**overrides):
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "exam_id": uuid4(),
        "enrollment_id": uuid4(),
        "student_id": uuid4(),
        "class_id": uuid4(),
        "admission_number": "ADM-001",
        "display_name": "Ada Lovelace",
        "status": CandidateStatus.ELIGIBLE,
        "status_reason": None,
        "roster_version": 1,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class CandidateReadServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_can_get_candidate(self) -> None:
        db = AsyncMock()
        row = candidate()
        current_exam = SimpleNamespace(id=row.exam_id)

        with (
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
        ):
            result = await CandidateService.get_candidate(
                db,
                actor=actor(),
                candidate_id=row.id,
            )

        self.assertEqual(result.id, row.id)
        self.assertEqual(result.exam_id, row.exam_id)

    async def test_assigned_invigilator_can_get_candidate(self) -> None:
        db = AsyncMock()
        teacher_id = uuid4()
        row = candidate()
        current_exam = SimpleNamespace(id=row.exam_id)

        with (
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
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
        ):
            result = await CandidateService.get_candidate(
                db,
                actor=actor(role="teacher", membership_id=teacher_id),
                candidate_id=row.id,
            )

        self.assertEqual(result.id, row.id)
        get_invigilator.assert_awaited_once_with(db, row.exam_id, teacher_id)

    async def test_unrelated_teacher_cannot_get_candidate(self) -> None:
        db = AsyncMock()
        row = candidate()
        current_exam = SimpleNamespace(id=row.exam_id)

        with (
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
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
            self.assertRaises(AcademicAuthorizationError),
        ):
            await CandidateService.get_candidate(
                db,
                actor=actor(role="teacher"),
                candidate_id=row.id,
            )


if __name__ == "__main__":
    unittest.main()
