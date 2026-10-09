from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

os.environ["DEBUG"] = "false"

from app.workers import results


class ResultWorkerReportingTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejections_and_existing_failures_are_reported(self):
        exam_id = uuid4()
        db = AsyncMock()
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=db)
        session.__aexit__ = AsyncMock(return_value=False)
        reason = (
            "TEACHER_ASSIGNMENT_NOT_FOUND: No teacher assignment covered the exam date."
        )
        response = SimpleNamespace(
            batch_id=uuid4(),
            received=1,
            applied=0,
            unchanged=0,
            rejected=1,
            errors=[
                SimpleNamespace(
                    code="TEACHER_ASSIGNMENT_NOT_FOUND",
                    detail="No teacher assignment covered the exam date.",
                )
            ],
        )
        for responses in ([response, None], [None]):
            with (
                self.subTest(fresh_rejection=len(responses) == 2),
                patch.object(results, "async_session_factory", return_value=session),
                patch.object(
                    results.ExamExecutionService,
                    "results_are_approved",
                    new=AsyncMock(return_value=True),
                ),
                patch.object(
                    results.approved_result_sync_service,
                    "sync_next_batch",
                    new=AsyncMock(side_effect=responses),
                ),
                patch.object(
                    results.ResultRepository,
                    "list_results_for_exam",
                    new=AsyncMock(
                        return_value=[
                            SimpleNamespace(voided_at=None, sync_error=reason)
                        ]
                    ),
                ),
                self.assertLogs(results.logger, level="WARNING") as logs,
            ):
                await results.sync_exam_results({}, str(exam_id))
                output = " ".join(logs.output)
                self.assertIn("remains incomplete", output)
                self.assertIn(reason, output)
                if len(responses) == 2:
                    self.assertIn("Weave rejected", output)
