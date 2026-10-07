import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from pydantic import ValidationError

from app.core.exceptions import AcademicAuthorizationError
from app.domains.exams.batch_operations_service import ExamBatchOperationsService
from app.domains.exams.exceptions import ExamStateError
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.models import ExamStatus
from app.domains.exams.operations_service import ExamOperationsService
from app.domains.exams.service import ExamService
from app.domains.exams.timetable_router import apply_exam_operations_batch
from app.domains.exams.timetable_schemas import BatchExamOperationRequest
from app.domains.exams.timetable_service import ActivationPreflight
from app.workers.producer import arq_producer


class BatchExamOperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin = SimpleNamespace(role="admin", is_active=True)
        self.db = AsyncMock()
        self.ids = [uuid4(), uuid4()]

    def payload(self, operation="suspend", **kwargs):
        return BatchExamOperationRequest(
            operation=operation, exam_ids=self.ids, reason="Power outage", **kwargs
        )

    async def test_authorization_precedes_any_transition(self):
        with patch.object(ExamService, "suspend_exam", new=AsyncMock()) as suspend:
            with self.assertRaises(AcademicAuthorizationError):
                await ExamBatchOperationsService.apply(
                    self.db,
                    actor=SimpleNamespace(role="teacher", is_active=True),
                    payload=self.payload(),
                )
            suspend.assert_not_awaited()

    async def test_failed_item_rolls_back_and_does_not_stop_later_suspension(self):
        with patch.object(
            ExamService,
            "suspend_exam",
            new=AsyncMock(
                side_effect=[
                    ExamStateError("Already suspended"),
                    SimpleNamespace(status=ExamStatus.SUSPENDED),
                ]
            ),
        ) as suspend:
            results = await ExamBatchOperationsService.apply(
                self.db, actor=self.admin, payload=self.payload()
            )
        self.assertFalse(results[0].succeeded)
        self.assertEqual(results[0].error, "Already suspended")
        self.assertTrue(results[1].succeeded)
        self.assertEqual(suspend.await_count, 2)
        self.db.rollback.assert_awaited_once()
        self.assertEqual(suspend.await_args.kwargs["reason"], "Power outage")

    async def test_resume_uses_canonical_transition(self):
        with patch.object(
            ExamService,
            "resume_exam",
            new=AsyncMock(return_value=SimpleNamespace(status=ExamStatus.ACTIVE)),
        ) as resume:
            results = await ExamBatchOperationsService.apply(
                self.db, actor=self.admin, payload=self.payload("resume")
            )
        self.assertTrue(all(result.succeeded for result in results))
        self.assertEqual(resume.await_count, 2)

    async def test_blocked_activation_returns_structured_preflight_without_starting(
        self,
    ):
        now = datetime.now(UTC)
        blocked = ActivationPreflight(
            exam_id=self.ids[0],
            checked_at=now,
            scheduled_start_at=now,
            proposed_activation_at=now,
            projected_end_at=None,
            delay_seconds=0,
            can_activate=False,
            blockers=("candidate_scope_conflict",),
            conflicting_operational_exam_ids=(self.ids[1],),
            affected_exams=(),
        )
        payload = BatchExamOperationRequest(
            operation="activate", exam_ids=[self.ids[0]]
        )
        with (
            patch.object(
                ExamOperationsService,
                "activation_preflight",
                new=AsyncMock(return_value=blocked),
            ),
            patch.object(ExamService, "activate_exam", new=AsyncMock()) as activate,
        ):
            response = await apply_exam_operations_batch(payload, self.db, self.admin)
        self.assertFalse(response.results[0].succeeded)
        self.assertEqual(
            response.results[0].preflight.blockers, ("candidate_scope_conflict",)
        )
        activate.assert_not_awaited()
        self.db.rollback.assert_awaited_once()

    async def test_activation_checks_each_item_after_previous_transition(self):
        calls = []

        async def check(_db, **kwargs):
            calls.append(("check", kwargs["exam_id"]))
            if kwargs["exam_id"] == self.ids[1]:
                raise ExamStateError("Candidates became occupied")
            return SimpleNamespace(can_activate=True)

        async def start(_db, **kwargs):
            calls.append(("activate", kwargs["exam_id"]))
            return SimpleNamespace(status=ExamStatus.ACTIVE)

        with (
            patch.object(
                ExamOperationsService,
                "activation_preflight",
                new=AsyncMock(side_effect=check),
            ),
            patch.object(
                ExamService, "activate_exam", new=AsyncMock(side_effect=start)
            ),
        ):
            results = await ExamBatchOperationsService.apply(
                self.db, actor=self.admin, payload=self.payload("activate")
            )
        self.assertEqual(
            calls,
            [("check", self.ids[0]), ("activate", self.ids[0]), ("check", self.ids[1])],
        )
        self.assertTrue(results[0].succeeded)
        self.assertFalse(results[1].succeeded)

    async def test_terminal_requests_remain_saved_when_enqueue_fails(self):
        for operation, method, status, job in [
            ("close", "request_close", ExamStatus.CLOSING, "finalize_exam_close"),
            (
                "cancel",
                "request_cancel",
                ExamStatus.CANCELLING,
                "finalize_exam_cancellation",
            ),
        ]:
            with (
                self.subTest(operation=operation),
                patch.object(
                    ExamExecutionService,
                    method,
                    new=AsyncMock(return_value=SimpleNamespace(status=status)),
                ),
                patch.object(
                    arq_producer,
                    "enqueue",
                    new=AsyncMock(side_effect=RuntimeError("Queue unavailable")),
                ) as enqueue,
            ):
                results = await ExamBatchOperationsService.apply(
                    self.db, actor=self.admin, payload=self.payload(operation)
                )
                self.assertTrue(all(result.succeeded for result in results))
                self.assertTrue(all(result.warning for result in results))
                self.assertEqual(enqueue.await_args.args, (job, str(self.ids[1])))

    async def test_route_rejects_non_admin(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as captured:
            await apply_exam_operations_batch(
                self.payload(), self.db, SimpleNamespace(role="teacher", is_active=True)
            )
        self.assertEqual(captured.exception.status_code, 403)

    def test_request_rejects_duplicates_empty_reason_and_oversized_batches(self):
        for changes in [
            {"exam_ids": [self.ids[0], self.ids[0]]},
            {"reason": "   "},
            {"exam_ids": [uuid4() for _ in range(101)]},
            {"operation": "delete"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                BatchExamOperationRequest(
                    **{
                        "operation": "suspend",
                        "exam_ids": self.ids,
                        "reason": "Power outage",
                        **changes,
                    }
                )
