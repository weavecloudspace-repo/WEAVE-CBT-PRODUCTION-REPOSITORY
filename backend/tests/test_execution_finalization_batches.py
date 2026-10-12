from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["DEBUG"] = "false"

from app.domains.attempts.models import AttemptEndReason, AttemptStatus
from app.domains.attempts.repository import AttemptRepository
from app.domains.attempts.service import AttemptService
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.execution_models import (
    ExamExecutionOperation,
    ExamResultDisposition,
)
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.execution_service import (
    FINALIZATION_BATCH_SIZE,
    ExamExecutionService,
)
from app.domains.exams.models import ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.results.service import ResultService


def _attempts(count: int):
    return [
        SimpleNamespace(
            id=uuid4(),
            candidate_id=uuid4(),
            status=AttemptStatus.IN_PROGRESS,
            ended_at=None,
            end_reason=None,
            termination_reason=None,
            active_since=datetime.now(UTC),
        )
        for _ in range(count)
    ]


def _batches(rows: list, size: int = FINALIZATION_BATCH_SIZE):
    return [rows[index : index + size] for index in range(0, len(rows), size)] + [[]]


class ExecutionFinalizationBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_finalizes_large_exam_in_recoverable_batches(self) -> None:
        db = AsyncMock()
        actor_id = uuid4()
        cutoff = datetime.now(UTC)
        exam = SimpleNamespace(
            id=uuid4(),
            status=ExamStatus.CLOSING,
            closed_by_actor_id=None,
            closed_at=None,
        )
        control = SimpleNamespace(
            operation=ExamExecutionOperation.CLOSING,
            operation_requested_at=cutoff,
            operation_requested_by_actor_id=actor_id,
            operation_reason=None,
            operation_error=None,
            result_disposition=None,
            results_decided_at=None,
            results_decided_by_actor_id=None,
            results_decision_reason=None,
        )
        rows = _attempts(450)

        async def candidate(_db, candidate_id, **_kwargs):
            return SimpleNamespace(id=candidate_id)

        with (
            patch.object(
                ExamExecutionService,
                "_prepare_operation_attempt",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=exam),
            ),
            patch.object(
                ExamExecutionRepository,
                "get_control",
                new=AsyncMock(return_value=control),
            ),
            patch.object(
                AttemptRepository,
                "list_attempts",
                new=AsyncMock(side_effect=_batches(rows)),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(side_effect=candidate),
            ),
            patch.object(
                AttemptService,
                "_checkpoint_active_segment",
                new=AsyncMock(),
            ),
            patch.object(AttemptRepository, "save_attempt", new=AsyncMock()),
            patch.object(
                ResultService,
                "calculate_for_submitted_attempt",
                new=AsyncMock(),
            ) as calculate,
            patch.object(
                ExamExecutionService,
                "_revoke_candidate_sessions",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "get_open_suspension_for_exam",
                new=AsyncMock(return_value=None),
            ),
            patch.object(ExamRepository, "save_exam", new=AsyncMock()),
            patch.object(ExamExecutionRepository, "save_control", new=AsyncMock()),
            patch.object(ExamExecutionService, "_add_event", new=AsyncMock()),
        ):
            result = await ExamExecutionService.finalize_close(db, exam_id=exam.id)

        self.assertIs(result, exam)
        self.assertEqual(exam.status, ExamStatus.CLOSED)
        self.assertEqual(
            control.result_disposition, ExamResultDisposition.PENDING_REVIEW
        )
        self.assertEqual(calculate.await_count, 450)
        self.assertTrue(all(row.status == AttemptStatus.SUBMITTED for row in rows))
        self.assertTrue(
            all(row.end_reason == AttemptEndReason.EXAM_CLOSED for row in rows)
        )
        # Three candidate batches plus the final CLOSED transaction.
        self.assertGreaterEqual(db.commit.await_count, 4)

    async def test_cancel_large_exam_terminates_without_calculating_results(
        self,
    ) -> None:
        db = AsyncMock()
        actor_id = uuid4()
        cutoff = datetime.now(UTC)
        exam = SimpleNamespace(
            id=uuid4(),
            status=ExamStatus.CANCELLING,
            cancelled_by_actor_id=None,
            cancelled_at=None,
            cancellation_reason=None,
        )
        control = SimpleNamespace(
            operation=ExamExecutionOperation.CANCELLING,
            operation_requested_at=cutoff,
            operation_requested_by_actor_id=actor_id,
            operation_reason="Paper compromised",
            operation_error=None,
            result_disposition=None,
            results_decided_at=None,
            results_decided_by_actor_id=None,
            results_decision_reason=None,
        )
        rows = _attempts(450)

        with (
            patch.object(
                ExamExecutionService,
                "_prepare_operation_attempt",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=exam),
            ),
            patch.object(
                ExamExecutionRepository,
                "get_control",
                new=AsyncMock(return_value=control),
            ),
            patch.object(
                AttemptRepository,
                "list_attempts",
                new=AsyncMock(side_effect=_batches(rows)),
            ),
            patch.object(
                AttemptService,
                "_checkpoint_active_segment",
                new=AsyncMock(),
            ),
            patch.object(AttemptRepository, "save_attempt", new=AsyncMock()),
            patch.object(
                ExamExecutionService,
                "_revoke_candidate_sessions",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "get_open_suspension_for_exam",
                new=AsyncMock(return_value=None),
            ),
            patch.object(ExamRepository, "save_exam", new=AsyncMock()),
            patch.object(ExamExecutionRepository, "save_control", new=AsyncMock()),
            patch.object(ExamExecutionService, "_add_event", new=AsyncMock()),
            patch.object(
                ResultService,
                "calculate_for_submitted_attempt",
                new=AsyncMock(),
            ) as calculate,
        ):
            result = await ExamExecutionService.finalize_cancellation(
                db,
                exam_id=exam.id,
            )

        self.assertIs(result, exam)
        self.assertEqual(exam.status, ExamStatus.CANCELLED)
        self.assertEqual(control.result_disposition, ExamResultDisposition.VOIDED)
        self.assertTrue(all(row.status == AttemptStatus.TERMINATED for row in rows))
        self.assertTrue(
            all(row.end_reason == AttemptEndReason.EXAM_CANCELLED for row in rows)
        )
        calculate.assert_not_awaited()
        self.assertGreaterEqual(db.commit.await_count, 4)


if __name__ == "__main__":
    unittest.main()
