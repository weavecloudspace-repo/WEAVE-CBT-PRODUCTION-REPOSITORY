from __future__ import annotations

import os
import unittest
from datetime import date
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
from app.domains.results.sync_service import ResultSyncService
from app.integrations.weave.exceptions import WeaveRequestRejectedError


class ResultSyncApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_but_unapproved_exam_cannot_claim_result_work(self) -> None:
        db = AsyncMock()
        exam_id = uuid4()
        current_exam = SimpleNamespace(id=exam_id, status=ExamStatus.CLOSED)
        control = SimpleNamespace(
            result_disposition=ExamResultDisposition.PENDING_REVIEW
        )
        service = ResultSyncService()

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
            patch.object(
                ResultRepository,
                "get_retryable_sync_batch_id_for_exam",
                new=AsyncMock(),
            ) as retry_batch,
            patch.object(
                ResultRepository,
                "list_pending_results_for_exam_sync",
                new=AsyncMock(),
            ) as pending_rows,
        ):
            batch_id = await service._claim_or_resume_batch(
                db,
                exam_id=exam_id,
                limit=1000,
            )

        self.assertIsNone(batch_id)
        retry_batch.assert_not_awaited()
        pending_rows.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_approved_exam_can_claim_fresh_result_batch(self) -> None:
        db = AsyncMock()
        exam_id = uuid4()
        current_exam = SimpleNamespace(id=exam_id, status=ExamStatus.CLOSED)
        control = SimpleNamespace(result_disposition=ExamResultDisposition.APPROVED)
        row = SimpleNamespace(
            exam_date=date(2026, 10, 7),
            sync_status=ResultSyncStatus.PENDING,
            sync_batch_id=None,
            sync_attempts=0,
            last_sync_attempt_at=None,
            sync_error=None,
            synced_at=None,
        )
        later_row = SimpleNamespace(**vars(row))
        later_row.exam_date = date(2026, 10, 8)
        service = ResultSyncService()

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
            patch.object(
                ResultRepository,
                "get_retryable_sync_batch_id_for_exam",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                ResultRepository,
                "list_pending_results_for_exam_sync",
                new=AsyncMock(return_value=[row, later_row]),
            ),
            patch.object(
                ResultRepository,
                "save_results",
                new=AsyncMock(),
            ),
        ):
            batch_id = await service._claim_or_resume_batch(
                db,
                exam_id=exam_id,
                limit=1000,
            )

        self.assertIsNotNone(batch_id)
        self.assertEqual(row.sync_status, ResultSyncStatus.SYNCING)
        self.assertEqual(row.sync_batch_id, batch_id)
        self.assertEqual(row.sync_attempts, 1)
        self.assertEqual(later_row.sync_status, ResultSyncStatus.PENDING)
        self.assertIsNone(later_row.sync_batch_id)
        db.commit.assert_awaited_once()


class ResultSyncFailureClassificationTests(unittest.IsolatedAsyncioTestCase):
    def test_http_rejection_classification(self) -> None:
        for status_code in (408, 409, 425, 429, 500, 503):
            with self.subTest(status_code=status_code):
                exc = WeaveRequestRejectedError(
                    status_code=status_code,
                    detail="temporary",
                )
                self.assertTrue(
                    ResultSyncService._rejection_requires_same_batch_retry(exc)
                )

        for status_code in (400, 401, 403, 404, 413, 422):
            with self.subTest(status_code=status_code):
                exc = WeaveRequestRejectedError(
                    status_code=status_code,
                    detail="definitive",
                )
                self.assertFalse(
                    ResultSyncService._rejection_requires_same_batch_retry(exc)
                )

    async def test_permanent_http_rejection_detaches_batch(self) -> None:
        db = AsyncMock()
        batch_id = uuid4()
        identity_store = SimpleNamespace(
            load=MagicMock(return_value=SimpleNamespace(server_credential="credential"))
        )
        gateway = SimpleNamespace(
            submit_results=AsyncMock(
                side_effect=WeaveRequestRejectedError(
                    status_code=422,
                    detail="invalid academic payload",
                )
            )
        )
        service = ResultSyncService(gateway=gateway, identity_store=identity_store)
        prepared = SimpleNamespace(payload=SimpleNamespace())

        with (
            patch.object(
                service,
                "_claim_or_resume_batch",
                new=AsyncMock(return_value=batch_id),
            ),
            patch.object(
                service,
                "_prepare_batch",
                new=AsyncMock(return_value=prepared),
            ),
            patch.object(
                service,
                "_mark_batch_failed",
                new=AsyncMock(),
            ) as mark_failed,
            self.assertRaises(WeaveRequestRejectedError),
        ):
            await service.sync_next_batch(db, exam_id=uuid4())

        self.assertFalse(mark_failed.await_args.kwargs["preserve_batch"])

    async def test_uncertain_http_rejection_preserves_batch(self) -> None:
        db = AsyncMock()
        batch_id = uuid4()
        identity_store = SimpleNamespace(
            load=MagicMock(return_value=SimpleNamespace(server_credential="credential"))
        )
        gateway = SimpleNamespace(
            submit_results=AsyncMock(
                side_effect=WeaveRequestRejectedError(
                    status_code=503,
                    detail="service unavailable",
                )
            )
        )
        service = ResultSyncService(gateway=gateway, identity_store=identity_store)
        prepared = SimpleNamespace(payload=SimpleNamespace())

        with (
            patch.object(
                service,
                "_claim_or_resume_batch",
                new=AsyncMock(return_value=batch_id),
            ),
            patch.object(
                service,
                "_prepare_batch",
                new=AsyncMock(return_value=prepared),
            ),
            patch.object(
                service,
                "_mark_batch_failed",
                new=AsyncMock(),
            ) as mark_failed,
            self.assertRaises(WeaveRequestRejectedError),
        ):
            await service.sync_next_batch(db, exam_id=uuid4())

        self.assertTrue(mark_failed.await_args.kwargs["preserve_batch"])


if __name__ == "__main__":
    unittest.main()
