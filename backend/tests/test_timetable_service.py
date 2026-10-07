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

from app.domains.academics.repository import AcademicRepository
from app.domains.exams.exceptions import ExamStateError
from app.domains.exams.models import ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.exams.timetable_service import ExamTimetableService


class TimetableIntervalTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)

    def test_overlapping_same_level_slots_conflict(self):
        self.assertTrue(
            ExamTimetableService.intervals_overlap(
                self.start,
                self.start + timedelta(hours=1),
                self.start + timedelta(minutes=30),
                self.start + timedelta(hours=1, minutes=30),
            )
        )

    def test_touching_slots_do_not_overlap(self):
        self.assertFalse(
            ExamTimetableService.intervals_overlap(
                self.start,
                self.start + timedelta(hours=1),
                self.start + timedelta(hours=1),
                self.start + timedelta(hours=2),
            )
        )

    def test_planned_end_uses_latest_normal_start_when_present(self):
        latest = self.start + timedelta(minutes=20)
        self.assertEqual(
            ExamTimetableService.planned_end_at(
                scheduled_start_at=self.start,
                latest_normal_start_at=latest,
                duration_minutes=60,
            ),
            self.start + timedelta(hours=1, minutes=20),
        )

    def test_planned_end_falls_back_to_scheduled_start(self):
        self.assertEqual(
            ExamTimetableService.planned_end_at(
                scheduled_start_at=self.start,
                latest_normal_start_at=None,
                duration_minutes=60,
            ),
            self.start + timedelta(hours=1),
        )


class TimetableDeliveryScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlapping_time_is_allowed_for_disjoint_delivery_classes(self):
        db = AsyncMock()
        session_id = uuid4()
        term_id = uuid4()
        subject_id = uuid4()
        level_id = uuid4()
        science_class_id = uuid4()
        arts_class_id = uuid4()
        start = datetime.now(UTC) + timedelta(days=1)
        other = SimpleNamespace(
            id=uuid4(),
            session_id=session_id,
            term_id=term_id,
            curriculum_subject_id=uuid4(),
            status=ExamStatus.DRAFT,
            scheduled_start_at=start,
            latest_normal_start_at=None,
            duration_minutes=60,
            title="SS1 Literature",
        )

        with (
            patch.object(
                AcademicRepository,
                "get_curriculum_subject_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        is_active=True,
                        is_elective=False,
                        elective_group_id=None,
                    )
                ),
            ),
            patch.object(
                ExamTimetableService,
                "level_id",
                new=AsyncMock(return_value=level_id),
            ),
            patch.object(
                ExamTimetableService,
                "acquire_level_lock",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "list_leaf_exams",
                new=AsyncMock(return_value=[other]),
            ),
            patch.object(
                ExamTimetableService,
                "_derived_delivery_class_ids",
                new=AsyncMock(
                    side_effect=[{science_class_id}, {arts_class_id}],
                ),
            ),
        ):
            await ExamTimetableService.require_planned_slot_available(
                db,
                session_id=session_id,
                term_id=term_id,
                curriculum_subject_id=subject_id,
                scheduled_start_at=start,
                duration_minutes=60,
            )

    async def test_overlapping_time_is_blocked_for_overlapping_delivery_classes(self):
        db = AsyncMock()
        session_id = uuid4()
        term_id = uuid4()
        subject_id = uuid4()
        level_id = uuid4()
        shared_class_id = uuid4()
        start = datetime(2026, 10, 8, 7, 0, tzinfo=UTC)
        other = SimpleNamespace(
            id=uuid4(),
            session_id=session_id,
            term_id=term_id,
            curriculum_subject_id=uuid4(),
            status=ExamStatus.DRAFT,
            scheduled_start_at=start,
            latest_normal_start_at=start + timedelta(minutes=20),
            duration_minutes=60,
            title="SS1 English",
        )
        later = SimpleNamespace(
            **{
                **vars(other),
                "id": uuid4(),
                "title": "SS1 Literature",
                "scheduled_start_at": start + timedelta(minutes=30),
                "latest_normal_start_at": None,
            }
        )

        with (
            patch.object(
                AcademicRepository,
                "get_curriculum_subject_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        is_active=True,
                        is_elective=False,
                        elective_group_id=None,
                    )
                ),
            ),
            patch.object(
                ExamTimetableService,
                "level_id",
                new=AsyncMock(return_value=level_id),
            ),
            patch.object(
                ExamTimetableService,
                "acquire_level_lock",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "list_leaf_exams",
                new=AsyncMock(return_value=[later, other]),
            ),
            patch.object(
                ExamTimetableService,
                "_derived_delivery_class_ids",
                new=AsyncMock(
                    side_effect=[{shared_class_id}, {shared_class_id}],
                ),
            ),
            self.assertRaisesRegex(
                ExamStateError,
                "reserves shared students",
            ) as context,
        ):
            await ExamTimetableService.require_planned_slot_available(
                db,
                session_id=session_id,
                term_id=term_id,
                curriculum_subject_id=subject_id,
                scheduled_start_at=start,
                duration_minutes=60,
            )
        message = str(context.exception)
        self.assertIn("SS1 English", message)
        self.assertNotIn("SS1 Literature", message)
        self.assertIn("08 Oct 2026, 08:00 AM WAT", message)
        self.assertIn("08 Oct 2026, 09:20 AM WAT", message)
        self.assertIn("including the entry window", message)


class TimetableOperationalScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sealed_activation_delegates_to_full_preflight_guard(self):
        db = AsyncMock()
        current_exam = SimpleNamespace(
            id=uuid4(),
            status=ExamStatus.SEALED,
        )

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamTimetableService,
                "require_activation_clear",
                new=AsyncMock(),
            ) as require_clear,
        ):
            await ExamTimetableService.require_level_free(
                db,
                exam_id=current_exam.id,
            )

        require_clear.assert_awaited_once()
        self.assertEqual(require_clear.await_args.kwargs["exam_id"], current_exam.id)
        self.assertIn("proposed_activation_at", require_clear.await_args.kwargs)

    async def test_resume_allows_disjoint_candidate_rosters_with_one_exists_query(self):
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=False)
        current_exam = SimpleNamespace(
            id=uuid4(),
            status=ExamStatus.SUSPENDED,
            session_id=uuid4(),
            term_id=uuid4(),
            curriculum_subject_id=uuid4(),
        )
        level_id = uuid4()

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamTimetableService,
                "level_id",
                new=AsyncMock(return_value=level_id),
            ),
            patch.object(
                ExamTimetableService,
                "acquire_level_lock",
                new=AsyncMock(),
            ) as acquire_lock,
            patch.object(
                ExamTimetableService,
                "acquire_operational_candidate_lock",
                new=AsyncMock(),
            ) as acquire_candidate_lock,
            patch.object(
                ExamTimetableService,
                "list_leaf_exams",
                new=AsyncMock(),
            ) as list_leaf,
        ):
            await ExamTimetableService.require_level_free(
                db,
                exam_id=current_exam.id,
            )

        acquire_lock.assert_awaited_once_with(
            db,
            session_id=current_exam.session_id,
            term_id=current_exam.term_id,
            level_id=level_id,
        )
        acquire_candidate_lock.assert_awaited_once_with(db)
        db.scalar.assert_awaited_once()
        list_leaf.assert_not_awaited()
        statement = db.scalar.await_args.args[0]
        self.assertIn("EXISTS", str(statement).upper())

    async def test_resume_blocks_when_any_eligible_candidate_overlaps(self):
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=True)
        current_exam = SimpleNamespace(
            id=uuid4(),
            status=ExamStatus.SUSPENDED,
            session_id=uuid4(),
            term_id=uuid4(),
            curriculum_subject_id=uuid4(),
        )

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamTimetableService,
                "level_id",
                new=AsyncMock(return_value=uuid4()),
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
            self.assertRaisesRegex(
                ExamStateError,
                "eligible candidates are already assigned",
            ),
        ):
            await ExamTimetableService.require_level_free(
                db,
                exam_id=current_exam.id,
            )

        db.scalar.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
