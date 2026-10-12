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
from app.domains.exams.exceptions import ExamStateError
from app.domains.exams.models import ExamStatus
from app.domains.exams.operations_service import ExamOperationsService
from app.domains.exams.repository import ExamRepository
from app.domains.exams.service import ExamService
from app.domains.exams.timetable_schemas import BatchExamStartRequest
from app.domains.exams.timetable_service import (
    ActivationPreflight,
    ExamTimetableService,
)

EXPIRED_SCHEDULE_MESSAGE = (
    "This examination was scheduled for a previous date. "
    "Reschedule it before activation."
)


class ActivationScheduleDateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.level_id = uuid4()
        self.student_id = uuid4()
        self.admin = SimpleNamespace(id=uuid4(), role="admin", is_active=True)

    @staticmethod
    def exam(*, scheduled_start_at: datetime):
        return SimpleNamespace(
            id=uuid4(),
            title="Mathematics CA",
            status=ExamStatus.SEALED,
            session_id=uuid4(),
            term_id=uuid4(),
            curriculum_subject_id=uuid4(),
            scheduled_start_at=scheduled_start_at,
            latest_normal_start_at=None,
            duration_minutes=60,
            activated_at=None,
        )

    async def run_preflight(self, *, source, checked_at):
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=False)
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=source),
            ),
            patch.object(
                ExamTimetableService,
                "level_id",
                new=AsyncMock(return_value=self.level_id),
            ),
            patch.object(
                ExamTimetableService,
                "acquire_level_lock",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "acquire_operational_candidate_lock",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "list_leaf_exams",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                ExamTimetableService,
                "_scope_map_for_exams",
                new=AsyncMock(return_value={source.id: frozenset({self.student_id})}),
            ),
        ):
            return await ExamTimetableService.activation_preflight(
                db,
                exam_id=source.id,
                proposed_activation_at=checked_at,
                include_conflict_details=False,
                apply_recovery_buffer=False,
            )

    async def test_previous_wat_calendar_date_blocks_activation(self):
        # Both timestamps are still September 27 in UTC. In WAT, however, the
        # exam belongs to September 27 while activation is attempted on
        # September 28. This protects the business-date rule from a naive UTC
        # date comparison.
        source = self.exam(scheduled_start_at=datetime(2026, 9, 27, 22, 30, tzinfo=UTC))
        checked_at = datetime(2026, 9, 27, 23, 30, tzinfo=UTC)

        preflight = await self.run_preflight(source=source, checked_at=checked_at)

        self.assertFalse(preflight.can_activate)
        self.assertIn("schedule_date_expired", preflight.blockers)
        self.assertNotIn("too_early", preflight.blockers)
        self.assertEqual(preflight.delay_seconds, 3600)
        self.assertEqual(preflight.affected_exams, ())
        self.assertIsNone(preflight.suggestion_valid_until_at)

    async def test_same_wat_calendar_date_keeps_late_start_recovery_allowed(self):
        # The UTC date changes between these timestamps, but both are September
        # 28 in WAT. A same-day delayed sitting must therefore remain eligible
        # for the existing late-start/recovery workflow.
        source = self.exam(scheduled_start_at=datetime(2026, 9, 27, 23, 30, tzinfo=UTC))
        checked_at = datetime(2026, 9, 28, 0, 15, tzinfo=UTC)

        preflight = await self.run_preflight(source=source, checked_at=checked_at)

        self.assertTrue(preflight.can_activate)
        self.assertNotIn("schedule_date_expired", preflight.blockers)
        self.assertNotIn("too_early", preflight.blockers)
        self.assertEqual(preflight.delay_seconds, 2700)

    async def test_final_activation_guard_rejects_expired_schedule_date(self):
        exam_id = uuid4()
        checked_at = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
        blocked = ActivationPreflight(
            exam_id=exam_id,
            checked_at=checked_at,
            scheduled_start_at=checked_at - timedelta(days=1),
            proposed_activation_at=checked_at,
            projected_end_at=None,
            delay_seconds=86400,
            can_activate=False,
            blockers=("schedule_date_expired",),
            conflicting_operational_exam_ids=(),
            affected_exams=(),
        )
        db = AsyncMock()

        with (
            patch.object(
                ExamTimetableService,
                "activation_preflight",
                new=AsyncMock(return_value=blocked),
            ),
            self.assertRaisesRegex(
                ExamStateError,
                "scheduled date has passed",
            ),
        ):
            await ExamTimetableService.require_activation_clear(
                db,
                exam_id=exam_id,
                proposed_activation_at=checked_at,
            )

    async def test_direct_activation_route_returns_specific_expired_date_error(self):
        exam_id = uuid4()
        checked_at = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
        blocked = ActivationPreflight(
            exam_id=exam_id,
            checked_at=checked_at,
            scheduled_start_at=checked_at - timedelta(days=1),
            proposed_activation_at=checked_at,
            projected_end_at=None,
            delay_seconds=86400,
            can_activate=False,
            blockers=("schedule_date_expired",),
            conflicting_operational_exam_ids=(),
            affected_exams=(),
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
            ) as activate,
            self.assertRaises(HTTPException) as captured,
        ):
            await exam_router.activate_exam(exam_id, db, self.admin)

        detail = captured.exception.detail
        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(detail["code"], "activation_schedule_date_expired")
        self.assertEqual(detail["message"], EXPIRED_SCHEDULE_MESSAGE)
        self.assertIn("schedule_date_expired", detail["preflight"]["blockers"])
        activate.assert_not_awaited()

    async def test_batch_start_returns_specific_expired_date_message(self):
        exam_id = uuid4()
        checked_at = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
        blocked = ActivationPreflight(
            exam_id=exam_id,
            checked_at=checked_at,
            scheduled_start_at=checked_at - timedelta(days=1),
            proposed_activation_at=checked_at,
            projected_end_at=None,
            delay_seconds=86400,
            can_activate=False,
            blockers=("schedule_date_expired",),
            conflicting_operational_exam_ids=(),
            affected_exams=(),
        )
        db = AsyncMock()

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=SimpleNamespace(id=exam_id)),
            ),
            patch.object(
                ExamOperationsService,
                "activation_preflight",
                new=AsyncMock(return_value=blocked),
            ),
            patch.object(
                ExamService,
                "activate_exam",
                new=AsyncMock(),
            ) as activate,
        ):
            response = await timetable_router.start_exam_batch(
                BatchExamStartRequest(exam_ids=[exam_id]),
                db,
                self.admin,
            )

        self.assertFalse(response.results[0].started)
        self.assertEqual(response.results[0].error, EXPIRED_SCHEDULE_MESSAGE)
        activate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
