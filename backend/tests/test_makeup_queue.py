import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.attempts.models import AttemptStatus
from app.domains.candidates.makeup_service import CandidateMakeupService


class MakeupQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_in_progress_makeup_stays_at_front_after_authorization_consumed(self):
        student_id = uuid4()
        level_id = uuid4()
        first_candidate_id = uuid4()
        second_candidate_id = uuid4()
        first_exam_id = uuid4()
        second_exam_id = uuid4()
        rows = [
            (
                SimpleNamespace(id=uuid4(), consumed_at=object()),
                SimpleNamespace(id=first_candidate_id),
                SimpleNamespace(id=first_exam_id),
                level_id,
                SimpleNamespace(status=AttemptStatus.IN_PROGRESS),
            ),
            (
                SimpleNamespace(id=uuid4(), consumed_at=None),
                SimpleNamespace(id=second_candidate_id),
                SimpleNamespace(id=second_exam_id),
                level_id,
                None,
            ),
        ]
        with (
            patch.object(
                CandidateMakeupService,
                "_queue_rows",
                AsyncMock(return_value=rows),
            ),
            patch(
                "app.domains.candidates.makeup_service.ExamRepository.has_unfinished_scheduled_exam_for_level",
                AsyncMock(return_value=False),
            ),
        ):
            result = await CandidateMakeupService.resolve_queue(
                AsyncMock(),
                student_id=student_id,
                session_id=uuid4(),
                term_id=uuid4(),
            )

        self.assertTrue(result.available)
        self.assertTrue(result.resume_existing_attempt)
        self.assertEqual(result.next_candidate_id, first_candidate_id)
        self.assertEqual(result.pending_count, 2)

    async def test_makeups_remain_locked_while_normal_cycle_is_unfinished(self):
        level_id = uuid4()
        rows = [
            (
                SimpleNamespace(id=uuid4(), consumed_at=None),
                SimpleNamespace(id=uuid4()),
                SimpleNamespace(id=uuid4()),
                level_id,
                None,
            )
        ]
        with (
            patch.object(
                CandidateMakeupService,
                "_queue_rows",
                AsyncMock(return_value=rows),
            ),
            patch(
                "app.domains.candidates.makeup_service.ExamRepository.has_unfinished_scheduled_exam_for_level",
                AsyncMock(return_value=True),
            ),
        ):
            result = await CandidateMakeupService.resolve_queue(
                AsyncMock(),
                student_id=uuid4(),
                session_id=uuid4(),
                term_id=uuid4(),
            )

        self.assertFalse(result.available)
        self.assertIn("normal scheduled examination cycle", result.blocked_reason)


if __name__ == "__main__":
    unittest.main()
