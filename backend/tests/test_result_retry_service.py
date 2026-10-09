from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["DEBUG"] = "false"

from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.models import ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.results.models import ResultSyncStatus
from app.domains.results.repository import ResultRepository
from app.domains.results.retry_service import ResultRetryService


class ResultRetryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_detached_failed_rows_return_to_pending_without_losing_history(
        self,
    ) -> None:
        db = AsyncMock()
        exam_id = uuid4()
        current_exam = SimpleNamespace(id=exam_id, status=ExamStatus.CLOSED)
        control = SimpleNamespace(result_disposition=ExamResultDisposition.APPROVED)
        row = SimpleNamespace(
            id=uuid4(),
            sync_status=ResultSyncStatus.FAILED,
            sync_batch_id=None,
            sync_attempts=3,
            last_sync_attempt_at=MagicMock(),
            synced_at=None,
            sync_error="422: invalid academic payload",
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        db.execute = AsyncMock(return_value=result)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamExecutionRepository,
                "get_control",
                new=AsyncMock(return_value=control),
            ),
            patch.object(ResultRepository, "save_results", new=AsyncMock()) as save,
        ):
            count = await ResultRetryService.retry_detached_failures(
                db,
                actor=SimpleNamespace(id=uuid4(), role="admin", is_active=True),
                exam_id=exam_id,
            )

        self.assertEqual(count, 1)
        self.assertEqual(row.sync_status, ResultSyncStatus.PENDING)
        self.assertIsNone(row.sync_error)
        self.assertEqual(row.sync_attempts, 3)
        save.assert_awaited_once_with(db, [row])
        db.commit.assert_awaited_once()

    async def test_unapproved_exam_cannot_retry_failures(self) -> None:
        db = AsyncMock()
        exam_id = uuid4()
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=exam_id, status=ExamStatus.CLOSED)
                ),
            ),
            patch.object(
                ExamExecutionRepository,
                "get_control",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        result_disposition=ExamResultDisposition.VOIDED
                    )
                ),
            ),
            self.assertRaisesRegex(Exception, "APPROVED"),
        ):
            await ResultRetryService.retry_detached_failures(
                db,
                actor=SimpleNamespace(id=uuid4(), role="admin", is_active=True),
                exam_id=exam_id,
            )
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
