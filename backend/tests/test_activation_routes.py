import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from fastapi import HTTPException

from app.domains.exams import router as exam_router
from app.domains.exams import timetable_router
from app.domains.exams.models import ExamStatus
from app.domains.exams.operations_service import ExamOperationsService
from app.domains.exams.repository import ExamRepository
from app.domains.exams.service import ExamService
from app.domains.exams.timetable_schemas import BatchExamStartRequest
from app.domains.exams.timetable_service import (
    ActivationPreflight,
    ActivationScheduleImpact,
)


class ActivationRouteContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.admin = SimpleNamespace(id=uuid4(), role="admin", is_active=True)

    def preflight(self, exam_id, *, can_activate=True, impacts=(), blockers=()):
        return ActivationPreflight(
            exam_id=exam_id,
            checked_at=self.now,
            scheduled_start_at=self.now - timedelta(minutes=10),
            proposed_activation_at=self.now,
            projected_end_at=self.now + timedelta(hours=1),
            delay_seconds=600,
            can_activate=can_activate,
            blockers=tuple(blockers),
            conflicting_operational_exam_ids=(),
            affected_exams=tuple(impacts),
            suggestion_valid_until_at=(
                self.now + timedelta(minutes=5) if impacts else None
            ),
        )

    async def test_ui_preflight_explicitly_requests_buffered_recovery_suggestions(self):
        exam_id = uuid4()
        result = self.preflight(exam_id)
        db = AsyncMock()

        with patch.object(
            ExamOperationsService,
            "activation_preflight",
            new=AsyncMock(return_value=result),
        ) as preflight:
            response = await timetable_router.activation_preflight(
                exam_id,
                db,
                self.admin,
            )

        self.assertEqual(response.exam_id, exam_id)
        self.assertTrue(preflight.await_args.kwargs["suggest_recovery_times"])

    async def test_direct_activate_refuses_unresolved_schedule_impact(self):
        exam_id = uuid4()
        affected_id = uuid4()
        impact = ActivationScheduleImpact(
            exam_id=affected_id,
            title="Physics",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.now + timedelta(minutes=20),
            scheduled_end_at=self.now + timedelta(hours=1, minutes=20),
            suggested_start_at=self.now + timedelta(hours=1, minutes=5),
            suggested_end_at=self.now + timedelta(hours=2, minutes=5),
            delay_seconds=2700,
            blocked_by_exam_ids=(exam_id,),
            reason="Students remain occupied",
        )
        blocked = self.preflight(
            exam_id,
            can_activate=False,
            impacts=(impact,),
            blockers=("schedule_reschedule_required",),
        )
        db = AsyncMock()

        with (
            patch.object(
                ExamOperationsService,
                "activation_preflight",
                new=AsyncMock(return_value=blocked),
            ),
            patch.object(
                ExamService,
                "activate_exam",
                new=AsyncMock(),
            ) as activate,self.assertRaises(HTTPException) as captured
        ):
            await exam_router.activate_exam(exam_id, db, self.admin)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail["code"],
            "activation_schedule_impact",
        )
        self.assertEqual(
            captured.exception.detail["preflight"]["affected_exams"][0]["exam_id"],
            str(affected_id),
        )
        activate.assert_not_awaited()

    async def test_batch_start_no_longer_rejects_two_same_level_disjoint_exams(self):
        exam_ids = [uuid4(), uuid4()]
        db = AsyncMock()
        existing = {exam_id: SimpleNamespace(id=exam_id) for exam_id in exam_ids}

        async def get_exam(_db, *, exam_id, **_kwargs):
            return existing.get(exam_id)

        async def preflight(_db, *, exam_id, **_kwargs):
            return self.preflight(exam_id, can_activate=True)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(side_effect=get_exam),
            ),
            patch.object(
                ExamOperationsService,
                "activation_preflight",
                new=AsyncMock(side_effect=preflight),
            ) as preflight_call,
            patch.object(
                ExamService,
                "activate_exam",
                new=AsyncMock(side_effect=lambda *_args, **_kwargs: SimpleNamespace()),
            ) as activate,
        ):
            response = await timetable_router.start_exam_batch(
                BatchExamStartRequest(exam_ids=exam_ids),
                db,
                self.admin,
            )

        self.assertEqual([item.started for item in response.results], [True, True])
        self.assertEqual(activate.await_count, 2)
        self.assertEqual(preflight_call.await_count, 2)
        for call in preflight_call.await_args_list:
            self.assertFalse(call.kwargs["suggest_recovery_times"])

    async def test_batch_start_returns_conflict_per_exam_without_aborting_other_items(
        self,
    ):
        first, second = uuid4(), uuid4()
        db = AsyncMock()

        async def get_exam(_db, *, exam_id, **_kwargs):
            return SimpleNamespace(id=exam_id)

        async def preflight(_db, *, exam_id, **_kwargs):
            if exam_id == first:
                return self.preflight(
                    exam_id,
                    can_activate=False,
                    blockers=("candidate_scope_conflict",),
                )
            return self.preflight(exam_id, can_activate=True)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(side_effect=get_exam),
            ),
            patch.object(
                ExamOperationsService,
                "activation_preflight",
                new=AsyncMock(side_effect=preflight),
            ),
            patch.object(
                ExamService,
                "activate_exam",
                new=AsyncMock(return_value=SimpleNamespace()),
            ) as activate,
        ):
            response = await timetable_router.start_exam_batch(
                BatchExamStartRequest(exam_ids=[first, second]),
                db,
                self.admin,
            )

        self.assertFalse(response.results[0].started)
        self.assertIn(
            "candidates are already taking another examination",
            response.results[0].error,
        )
        self.assertTrue(response.results[1].started)
        activate.assert_awaited_once()
        self.assertEqual(activate.await_args.kwargs["exam_id"], second)


if __name__ == "__main__":
    unittest.main()
