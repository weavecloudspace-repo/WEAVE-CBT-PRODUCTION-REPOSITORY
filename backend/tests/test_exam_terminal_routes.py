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
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("WEAVE_API_BASE_URL", "https://weave.invalid")
os.environ["DEBUG"] = "false"

from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.router import cancel_exam, close_exam
from app.domains.exams.schemas import ExamReasonPayload, ExamResponse
from app.workers.producer import arq_producer


class ExamTerminalRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_route_stages_durable_close_and_queues_finalizer(self) -> None:
        exam_id = uuid4()
        current_exam = SimpleNamespace(id=exam_id)
        actor = SimpleNamespace(id=uuid4(), role="admin", is_active=True)
        db = AsyncMock()

        with (
            patch.object(
                ExamExecutionService,
                "request_close",
                new=AsyncMock(return_value=current_exam),
            ) as request_close,
            patch.object(arq_producer, "enqueue", new=AsyncMock()) as enqueue,
            patch.object(
                ExamResponse,
                "model_validate",
                return_value=current_exam,
            ),
        ):
            result = await close_exam(exam_id=exam_id, db=db, actor=actor)

        self.assertIs(result, current_exam)
        request_close.assert_awaited_once_with(
            db,
            actor=actor,
            exam_id=exam_id,
        )
        enqueue.assert_awaited_once_with("finalize_exam_close", str(exam_id))

    async def test_cancel_route_stages_durable_cancel_and_queues_finalizer(
        self,
    ) -> None:
        exam_id = uuid4()
        current_exam = SimpleNamespace(id=exam_id)
        actor = SimpleNamespace(id=uuid4(), role="admin", is_active=True)
        db = AsyncMock()
        payload = ExamReasonPayload(reason="Paper compromised")

        with (
            patch.object(
                ExamExecutionService,
                "request_cancel",
                new=AsyncMock(return_value=current_exam),
            ) as request_cancel,
            patch.object(arq_producer, "enqueue", new=AsyncMock()) as enqueue,
            patch.object(
                ExamResponse,
                "model_validate",
                return_value=current_exam,
            ),
        ):
            result = await cancel_exam(
                exam_id=exam_id,
                payload=payload,
                db=db,
                actor=actor,
            )

        self.assertIs(result, current_exam)
        request_cancel.assert_awaited_once_with(
            db,
            actor=actor,
            exam_id=exam_id,
            reason="Paper compromised",
        )
        enqueue.assert_awaited_once_with(
            "finalize_exam_cancellation",
            str(exam_id),
        )


if __name__ == "__main__":
    unittest.main()
