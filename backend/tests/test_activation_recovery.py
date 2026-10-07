import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.exams.exceptions import (
    ExamScheduleImpactError,
    ExamStateError,
)
from app.domains.exams.models import ExamRosterStatus, ExamStatus
from app.domains.exams.operations_service import ExamOperationsService
from app.domains.exams.repository import ExamRepository
from app.domains.exams.timetable_service import (
    ActivationPreflight,
    ActivationScheduleImpact,
    ExamTimetableService,
    _PlannedNode,
    _ScopeWindow,
)
from app.domains.runtime.repository import RuntimeRepository


class ActivationCascadeTests(unittest.TestCase):
    def setUp(self):
        self.day = datetime(2026, 9, 28, 11, 0, tzinfo=UTC)
        self.science = uuid4()
        self.arts = uuid4()
        self.commercial = uuid4()

    def source(self, *, class_ids=None, start=None, end=None):
        return _ScopeWindow(
            exam_id=uuid4(),
            title="Chemistry",
            class_ids=frozenset(class_ids or {self.science}),
            start_at=start or self.day + timedelta(minutes=40),
            end_at=end or self.day + timedelta(hours=1, minutes=40),
        )

    def planned(
        self,
        title,
        *,
        class_ids,
        start,
        minutes=60,
    ):
        return _PlannedNode(
            exam_id=uuid4(),
            title=title,
            status=ExamStatus.SEALED,
            class_ids=frozenset(class_ids),
            scheduled_start_at=start,
            window_duration=timedelta(minutes=minutes),
        )

    def test_delayed_science_exam_moves_science_but_not_parallel_arts(self):
        source = self.source()
        physics = self.planned(
            "Physics",
            class_ids={self.science},
            start=self.day + timedelta(hours=1),
        )
        government = self.planned(
            "Government",
            class_ids={self.arts},
            start=self.day + timedelta(hours=1),
        )

        impacts = ExamTimetableService._cascade_planned_windows(
            source_window=source,
            fixed_windows=[],
            planned_nodes=[physics, government],
            checked_at=self.day + timedelta(minutes=40),
        )

        self.assertEqual([row.title for row in impacts], ["Physics"])
        self.assertEqual(
            impacts[0].suggested_start_at,
            self.day + timedelta(hours=1, minutes=40),
        )

    def test_general_subject_merges_two_delayed_department_branches(self):
        source = self.source()
        literature = _ScopeWindow(
            exam_id=uuid4(),
            title="Literature",
            class_ids=frozenset({self.arts}),
            start_at=self.day + timedelta(minutes=30),
            end_at=self.day + timedelta(hours=1, minutes=30),
        )
        physics = self.planned(
            "Physics",
            class_ids={self.science},
            start=self.day + timedelta(hours=1),
        )
        government = self.planned(
            "Government",
            class_ids={self.arts},
            start=self.day + timedelta(hours=1),
        )
        english = self.planned(
            "English",
            class_ids={self.science, self.arts},
            start=self.day + timedelta(hours=2),
        )

        impacts = ExamTimetableService._cascade_planned_windows(
            source_window=source,
            fixed_windows=[literature],
            planned_nodes=[physics, government, english],
            checked_at=self.day + timedelta(minutes=40),
        )
        by_title = {row.title: row for row in impacts}

        self.assertEqual(
            by_title["Physics"].suggested_start_at,
            self.day + timedelta(hours=1, minutes=40),
        )
        self.assertEqual(
            by_title["Government"].suggested_start_at,
            self.day + timedelta(hours=1, minutes=30),
        )
        self.assertEqual(
            by_title["English"].suggested_start_at,
            self.day + timedelta(hours=2, minutes=40),
        )

    def test_delayed_general_subject_propagates_into_other_department(self):
        source = self.source()
        english = self.planned(
            "English",
            class_ids={self.science, self.arts},
            start=self.day + timedelta(hours=1),
        )
        government = self.planned(
            "Government",
            class_ids={self.arts},
            start=self.day + timedelta(hours=2),
        )

        impacts = ExamTimetableService._cascade_planned_windows(
            source_window=source,
            fixed_windows=[],
            planned_nodes=[english, government],
            checked_at=self.day + timedelta(minutes=40),
        )
        by_title = {row.title: row for row in impacts}

        self.assertEqual(
            by_title["English"].suggested_start_at,
            self.day + timedelta(hours=1, minutes=40),
        )
        self.assertEqual(
            by_title["Government"].suggested_start_at,
            self.day + timedelta(hours=2, minutes=40),
        )

    def test_multi_department_subject_conflicts_on_any_shared_department(self):
        source = self.source()
        agriculture = self.planned(
            "Agricultural Science",
            class_ids={self.science, self.commercial},
            start=self.day + timedelta(hours=1),
        )

        impacts = ExamTimetableService._cascade_planned_windows(
            source_window=source,
            fixed_windows=[],
            planned_nodes=[agriculture],
            checked_at=self.day + timedelta(minutes=40),
        )

        self.assertEqual(len(impacts), 1)
        self.assertEqual(impacts[0].title, "Agricultural Science")

    def test_touching_slots_are_not_shifted(self):
        source = _ScopeWindow(
            exam_id=uuid4(),
            title="Chemistry",
            class_ids=frozenset({self.science}),
            start_at=self.day,
            end_at=self.day + timedelta(hours=1),
        )
        physics = self.planned(
            "Physics",
            class_ids={self.science},
            start=self.day + timedelta(hours=1),
        )

        impacts = ExamTimetableService._cascade_planned_windows(
            source_window=source,
            fixed_windows=[],
            planned_nodes=[physics],
            checked_at=self.day,
        )

        self.assertEqual(impacts, ())

    def test_overdue_sealed_exam_is_not_silently_leapfrogged(self):
        source = self.source()
        overdue = self.planned(
            "Physics",
            class_ids={self.science},
            start=self.day - timedelta(hours=1),
        )

        impacts = ExamTimetableService._cascade_planned_windows(
            source_window=source,
            fixed_windows=[],
            planned_nodes=[overdue],
            checked_at=self.day + timedelta(minutes=40),
        )

        self.assertEqual(len(impacts), 1)
        self.assertEqual(impacts[0].suggested_start_at, source.end_at)
        self.assertIn(source.exam_id, impacts[0].blocked_by_exam_ids)

    def test_suspended_scope_makes_safe_time_unknown_and_propagates(self):
        source = self.source()
        suspended_arts = _ScopeWindow(
            exam_id=uuid4(),
            title="Literature",
            class_ids=frozenset({self.arts}),
            start_at=self.day + timedelta(minutes=20),
            end_at=None,
        )
        english = self.planned(
            "English",
            class_ids={self.science, self.arts},
            start=self.day + timedelta(hours=1),
        )
        government = self.planned(
            "Government",
            class_ids={self.arts},
            start=self.day + timedelta(hours=2),
        )

        impacts = ExamTimetableService._cascade_planned_windows(
            source_window=source,
            fixed_windows=[suspended_arts],
            planned_nodes=[english, government],
            checked_at=self.day + timedelta(minutes=40),
        )
        by_title = {row.title: row for row in impacts}

        self.assertIsNone(by_title["English"].suggested_start_at)
        self.assertIsNone(by_title["Government"].suggested_start_at)
        self.assertIn(suspended_arts.exam_id, by_title["English"].blocked_by_exam_ids)

    def test_late_entry_grace_is_part_of_projected_operational_end(self):
        exam = SimpleNamespace(
            scheduled_start_at=self.day,
            latest_normal_start_at=self.day + timedelta(minutes=20),
            duration_minutes=60,
        )

        projected = ExamTimetableService.projected_end_for_actual_start(
            exam,
            actual_start_at=self.day + timedelta(minutes=40),
        )

        self.assertEqual(projected, self.day + timedelta(hours=2))

    def test_completed_suspension_extends_projected_end(self):
        exam = SimpleNamespace(
            scheduled_start_at=self.day,
            latest_normal_start_at=None,
            duration_minutes=60,
        )

        projected = ExamTimetableService.projected_end_for_actual_start(
            exam,
            actual_start_at=self.day,
            completed_pause=timedelta(minutes=15),
        )

        self.assertEqual(projected, self.day + timedelta(hours=1, minutes=15))


class ActivationOperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.admin = SimpleNamespace(id=uuid4(), is_active=True, role="admin")
        self.source_id = uuid4()
        self.affected_id = uuid4()

    def preflight(self, *, impacts=(), blockers=(), can_activate=False):
        return ActivationPreflight(
            exam_id=self.source_id,
            checked_at=self.now,
            scheduled_start_at=self.now - timedelta(minutes=40),
            proposed_activation_at=self.now,
            projected_end_at=self.now + timedelta(hours=1),
            delay_seconds=2400,
            can_activate=can_activate,
            blockers=tuple(blockers),
            conflicting_operational_exam_ids=(),
            affected_exams=tuple(impacts),
        )

    def impact(self, *, suggested_start=None):
        return ActivationScheduleImpact(
            exam_id=self.affected_id,
            title="Physics",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.now + timedelta(minutes=20),
            scheduled_end_at=self.now + timedelta(hours=1, minutes=20),
            suggested_start_at=suggested_start or self.now + timedelta(hours=1),
            suggested_end_at=(suggested_start or self.now + timedelta(hours=1))
            + timedelta(hours=1),
            delay_seconds=2400,
            blocked_by_exam_ids=(self.source_id,),
            reason="conflict",
        )

    async def test_reschedule_rejects_unrelated_exam_id(self):
        db = AsyncMock()
        source = SimpleNamespace(id=self.source_id)
        current = self.preflight(
            impacts=(self.impact(),),
            blockers=("schedule_reschedule_required",),
        )
        unrelated = uuid4()

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=source),
            ),
            patch.object(
                ExamOperationsService,
                "_require_activation_static_readiness",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "activation_preflight",
                new=AsyncMock(return_value=current),
            ),self.assertRaisesRegex(
            ExamStateError,
            "current activation impact chain",
        )
        ):
            await ExamOperationsService.reschedule_activation_impact(
                db,
                actor=self.admin,
                source_exam_id=self.source_id,
                changes={unrelated: self.now + timedelta(hours=2)},
                reason="Recover timetable",
            )

    async def test_custom_schedule_is_rejected_if_simulation_still_conflicts(self):
        db = AsyncMock()
        source = SimpleNamespace(id=self.source_id)
        affected = SimpleNamespace(
            id=self.affected_id,
            status=ExamStatus.SEALED,
            scheduled_start_at=self.now + timedelta(minutes=20),
            latest_normal_start_at=None,
        )
        current = self.preflight(
            impacts=(self.impact(),),
            blockers=("schedule_reschedule_required",),
        )
        still_bad = self.preflight(
            impacts=(self.impact(suggested_start=self.now + timedelta(hours=2)),),
            blockers=("schedule_reschedule_required",),
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [affected]
        db.execute = AsyncMock(return_value=result)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=source),
            ),
            patch.object(
                ExamOperationsService,
                "_require_activation_static_readiness",
                new=AsyncMock(),
            ),
            patch.object(
                ExamOperationsService,
                "_require_latest_revision",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "activation_preflight",
                new=AsyncMock(side_effect=[current, still_bad]),
            ),self.assertRaises(ExamScheduleImpactError)
        ):
            await ExamOperationsService.reschedule_activation_impact(
                db,
                actor=self.admin,
                source_exam_id=self.source_id,
                changes={self.affected_id: self.now + timedelta(hours=1)},
                reason="Recover timetable",
            )

        db.commit.assert_not_awaited()

    async def test_successful_batch_preserves_existing_late_entry_grace(self):
        db = AsyncMock()
        source = SimpleNamespace(id=self.source_id)
        old_start = self.now + timedelta(minutes=20)
        affected = SimpleNamespace(
            id=self.affected_id,
            status=ExamStatus.SEALED,
            scheduled_start_at=old_start,
            latest_normal_start_at=old_start + timedelta(minutes=15),
        )
        current = self.preflight(
            impacts=(self.impact(),),
            blockers=("schedule_reschedule_required",),
        )
        clean = self.preflight(impacts=(), blockers=(), can_activate=True)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [affected]
        db.execute = AsyncMock(return_value=result)
        new_start = self.now + timedelta(hours=2)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=source),
            ),
            patch.object(
                ExamOperationsService,
                "_require_activation_static_readiness",
                new=AsyncMock(),
            ),
            patch.object(
                ExamOperationsService,
                "_require_latest_revision",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "activation_preflight",
                new=AsyncMock(side_effect=[current, clean]),
            ),
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, exam: exam),
            ) as save_exam,
            patch.object(
                RuntimeRepository,
                "add_outbox_event",
                new=AsyncMock(),
            ) as add_event,
        ):
            exams, returned = await ExamOperationsService.reschedule_activation_impact(
                db,
                actor=self.admin,
                source_exam_id=self.source_id,
                changes={self.affected_id: new_start},
                reason="Server outage delayed the previous sitting",
            )

        self.assertEqual(exams, [affected])
        self.assertIs(returned, clean)
        self.assertEqual(affected.scheduled_start_at, new_start)
        self.assertEqual(
            affected.latest_normal_start_at,
            new_start + timedelta(minutes=15),
        )
        save_exam.assert_awaited_once()
        add_event.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_candidate_conflict_cannot_be_solved_by_rescheduling(self):
        db = AsyncMock()
        source = SimpleNamespace(id=self.source_id)
        current = self.preflight(
            impacts=(self.impact(),),
            blockers=("candidate_scope_conflict", "schedule_reschedule_required"),
        )

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=source),
            ),
            patch.object(
                ExamOperationsService,
                "_require_activation_static_readiness",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "activation_preflight",
                new=AsyncMock(return_value=current),
            ),self.assertRaisesRegex(ExamStateError, "cannot resolve candidates")
        ):
            await ExamOperationsService.reschedule_activation_impact(
                db,
                actor=self.admin,
                source_exam_id=self.source_id,
                changes={self.affected_id: self.now + timedelta(hours=2)},
                reason="Recover timetable",
            )

    async def test_non_sealed_downstream_exam_cannot_use_operational_reschedule(self):
        db = AsyncMock()
        source = SimpleNamespace(id=self.source_id)
        affected = SimpleNamespace(
            id=self.affected_id,
            status=ExamStatus.ACTIVE,
            scheduled_start_at=self.now + timedelta(minutes=20),
            latest_normal_start_at=None,
        )
        current = self.preflight(
            impacts=(self.impact(),),
            blockers=("schedule_reschedule_required",),
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [affected]
        db.execute = AsyncMock(return_value=result)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=source),
            ),
            patch.object(
                ExamOperationsService,
                "_require_activation_static_readiness",
                new=AsyncMock(),
            ),
            patch.object(
                ExamTimetableService,
                "activation_preflight",
                new=AsyncMock(return_value=current),
            ),self.assertRaisesRegex(ExamStateError, "Only SEALED")
        ):
            await ExamOperationsService.reschedule_activation_impact(
                db,
                actor=self.admin,
                source_exam_id=self.source_id,
                changes={self.affected_id: self.now + timedelta(hours=2)},
                reason="Recover timetable",
            )


class ActivationStaticReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_zero_entry_window_blocks_activation(self):
        start = datetime.now(UTC) + timedelta(hours=1)
        exam = SimpleNamespace(
            id=uuid4(),
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.READY,
            question_count=50,
            sealed_at=datetime.now(UTC),
            component_maximum_score=40,
            scheduled_start_at=start,
            latest_normal_start_at=start,
        )
        with (
            patch.object(
                ExamOperationsService, "_require_latest_revision", new=AsyncMock()
            ),
            patch.object(
                ExamRepository, "count_exam_questions", new=AsyncMock(return_value=50)
            ),
            self.assertRaisesRegex(ExamStateError, "Equal times leave no time"),
        ):
            await ExamOperationsService._require_activation_static_readiness(
                AsyncMock(), exam
            )

    async def test_stale_roster_blocks_preflight(self):
        exam = SimpleNamespace(
            id=uuid4(),
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.STALE,
        )
        db = AsyncMock()

        with patch.object(
            ExamOperationsService,
            "_require_latest_revision",
            new=AsyncMock(),
        ), self.assertRaisesRegex(ExamStateError, "roster must be READY"):
            await ExamOperationsService._require_activation_static_readiness(
                db, exam
            )

    async def test_frozen_question_mismatch_blocks_preflight(self):
        exam = SimpleNamespace(
            id=uuid4(),
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.READY,
            question_count=50,
            sealed_at=self_or_now(),
            component_maximum_score=40,
            scheduled_start_at=self_or_now() + timedelta(hours=1),
        )
        db = AsyncMock()

        with (
            patch.object(
                ExamOperationsService,
                "_require_latest_revision",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "count_exam_questions",
                new=AsyncMock(return_value=49),
            ),self.assertRaisesRegex(ExamStateError, "Frozen question count")
        ):
            await ExamOperationsService._require_activation_static_readiness(
                db, exam
            )


def self_or_now():
    return datetime.now(UTC)


if __name__ == "__main__":
    unittest.main()
