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

from app.domains.exams.models import ExamStatus
from app.domains.exams.operations_service import ExamOperationsService
from app.domains.exams.repository import ExamRepository
from app.domains.exams.timetable_service import (
    ACTIVATION_RECOVERY_BUFFER,
    ActivationPreflight,
    ExamTimetableService,
)


class ActivationPreflightTimingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.checked_at = datetime(2026, 9, 28, 11, 40, tzinfo=UTC)
        self.level_id = uuid4()
        self.science_class = uuid4()
        self.arts_class = uuid4()

    def exam(
        self,
        *,
        title: str,
        status: ExamStatus,
        scheduled_start_at: datetime | None,
        duration_minutes: int = 60,
        class_subject_id=None,
        activated_at: datetime | None = None,
    ):
        return SimpleNamespace(
            id=uuid4(),
            title=title,
            status=status,
            session_id=uuid4(),
            term_id=uuid4(),
            curriculum_subject_id=class_subject_id or uuid4(),
            scheduled_start_at=scheduled_start_at,
            latest_normal_start_at=None,
            duration_minutes=duration_minutes,
            activated_at=activated_at,
        )

    async def run_preflight(
        self,
        *,
        source,
        rows,
        scopes,
        at=None,
        overrides=None,
        buffered=True,
        ui=False,
    ):
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=False)
        with (
            patch.object(
                ExamOperationsService,
                "_require_activation_static_readiness",
                new=AsyncMock(),
            ),
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
                new=AsyncMock(return_value=rows),
            ),
            patch.object(
                ExamTimetableService,
                "_scope_map_for_exams",
                new=AsyncMock(return_value=scopes),
            ),
        ):
            if ui:
                return await ExamOperationsService.activation_preflight(
                    db,
                    actor=SimpleNamespace(role="admin", is_active=True),
                    exam_id=source.id,
                    proposed_activation_at=at or self.checked_at,
                    suggest_recovery_times=True,
                )
            return await ExamTimetableService.activation_preflight(
                db,
                exam_id=source.id,
                proposed_activation_at=at or self.checked_at,
                schedule_overrides=overrides,
                include_conflict_details=False,
                apply_recovery_buffer=buffered,
            )

    async def test_saved_recovery_remains_activatable_on_later_ui_check(self):
        source = self.exam(
            title="English",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=30),
        )
        later = self.exam(
            title="Literature",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        scopes = {
            source.id: frozenset({self.science_class}),
            later.id: frozenset({self.science_class}),
        }
        proposal = await self.run_preflight(
            source=source, rows=[later], scopes=scopes, ui=True
        )
        self.assertFalse(proposal.can_activate)
        later.scheduled_start_at = proposal.affected_exams[0].suggested_start_at
        later_check = self.checked_at + timedelta(seconds=13)
        # A fresh buffered simulation shifts the suggestion again, even though
        # the saved five-minute headroom is still safe for immediate activation.
        rolling = await self.run_preflight(
            source=source, rows=[later], scopes=scopes, at=later_check
        )
        self.assertFalse(rolling.can_activate)
        actual = await self.run_preflight(
            source=source, rows=[later], scopes=scopes, at=later_check, ui=True
        )
        self.assertTrue(actual.can_activate)
        self.assertEqual(actual.affected_exams, ())
        expired = await self.run_preflight(
            source=source,
            rows=[later],
            scopes=scopes,
            at=self.checked_at + timedelta(minutes=6),
            ui=True,
        )
        self.assertFalse(expired.can_activate)
        self.assertGreater(
            expired.affected_exams[0].suggested_start_at, later.scheduled_start_at
        )

    async def test_late_ui_preflight_reserves_five_minutes_of_recovery_headroom(self):
        source = self.exam(
            title="Chemistry",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=40),
        )
        physics = self.exam(
            title="Physics",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        scopes = {
            source.id: frozenset({self.science_class}),
            physics.id: frozenset({self.science_class}),
        }

        preflight = await self.run_preflight(
            source=source,
            rows=[physics],
            scopes=scopes,
            buffered=True,
        )

        self.assertFalse(preflight.can_activate)
        self.assertEqual(
            preflight.suggestion_valid_until_at,
            self.checked_at + ACTIVATION_RECOVERY_BUFFER,
        )
        self.assertEqual(len(preflight.affected_exams), 1)
        self.assertEqual(
            preflight.affected_exams[0].suggested_start_at,
            self.checked_at + ACTIVATION_RECOVERY_BUFFER + timedelta(hours=1),
        )

    async def test_enforcement_mode_uses_real_activation_time_without_rolling_buffer(
        self,
    ):
        source = self.exam(
            title="Chemistry",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=40),
        )
        physics = self.exam(
            title="Physics",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        scopes = {
            source.id: frozenset({self.science_class}),
            physics.id: frozenset({self.science_class}),
        }

        preflight = await self.run_preflight(
            source=source,
            rows=[physics],
            scopes=scopes,
            buffered=False,
        )

        self.assertIsNone(preflight.suggestion_valid_until_at)
        self.assertEqual(
            preflight.affected_exams[0].suggested_start_at,
            self.checked_at + timedelta(hours=1),
        )

    async def test_buffered_suggestion_remains_valid_if_admin_activates_within_window(
        self,
    ):
        source = self.exam(
            title="Chemistry",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=40),
        )
        physics = self.exam(
            title="Physics",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        scopes = {
            source.id: frozenset({self.science_class}),
            physics.id: frozenset({self.science_class}),
        }

        suggestion = await self.run_preflight(
            source=source,
            rows=[physics],
            scopes=scopes,
            buffered=True,
        )
        suggested_start = suggestion.affected_exams[0].suggested_start_at
        self.assertIsNotNone(suggested_start)

        enforcement = await self.run_preflight(
            source=source,
            rows=[physics],
            scopes=scopes,
            at=self.checked_at + timedelta(minutes=3),
            overrides={physics.id: suggested_start},
            buffered=False,
        )

        self.assertTrue(enforcement.can_activate)
        self.assertEqual(enforcement.affected_exams, ())

    async def test_buffered_suggestion_expires_if_activation_waits_too_long(self):
        source = self.exam(
            title="Chemistry",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=40),
        )
        physics = self.exam(
            title="Physics",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        scopes = {
            source.id: frozenset({self.science_class}),
            physics.id: frozenset({self.science_class}),
        }

        suggestion = await self.run_preflight(
            source=source,
            rows=[physics],
            scopes=scopes,
            buffered=True,
        )
        suggested_start = suggestion.affected_exams[0].suggested_start_at

        enforcement = await self.run_preflight(
            source=source,
            rows=[physics],
            scopes=scopes,
            at=self.checked_at + timedelta(minutes=6),
            overrides={physics.id: suggested_start},
            buffered=False,
        )

        self.assertFalse(enforcement.can_activate)
        self.assertIn("schedule_reschedule_required", enforcement.blockers)

    async def test_too_early_activation_is_blocked_without_creating_a_delay_chain(self):
        source = self.exam(
            title="Chemistry",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        scopes = {source.id: frozenset({self.science_class})}

        preflight = await self.run_preflight(
            source=source,
            rows=[],
            scopes=scopes,
            buffered=True,
        )

        self.assertFalse(preflight.can_activate)
        self.assertIn("too_early", preflight.blockers)
        self.assertEqual(preflight.affected_exams, ())

    async def test_late_department_exam_does_not_move_disjoint_department_exam(self):
        source = self.exam(
            title="Chemistry",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=40),
        )
        literature = self.exam(
            title="Literature",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        scopes = {
            source.id: frozenset({self.science_class}),
            literature.id: frozenset({self.arts_class}),
        }

        preflight = await self.run_preflight(
            source=source,
            rows=[literature],
            scopes=scopes,
            buffered=True,
        )

        self.assertTrue(preflight.can_activate)
        self.assertEqual(preflight.affected_exams, ())

    async def test_overdue_parallel_departments_merge_safely_into_general_subject(self):
        source = self.exam(
            title="Chemistry",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=40),
        )
        literature = self.exam(
            title="Literature",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=40),
        )
        physics = self.exam(
            title="Physics",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        government = self.exam(
            title="Government",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        english = self.exam(
            title="English",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(hours=1, minutes=20),
        )
        scopes = {
            source.id: frozenset({self.science_class}),
            literature.id: frozenset({self.arts_class}),
            physics.id: frozenset({self.science_class}),
            government.id: frozenset({self.arts_class}),
            english.id: frozenset({self.science_class, self.arts_class}),
        }

        preflight = await self.run_preflight(
            source=source,
            rows=[literature, physics, government, english],
            scopes=scopes,
            buffered=False,
        )
        impacts = {impact.exam_id: impact for impact in preflight.affected_exams}

        # Chemistry and the still-pending Literature sitting are both projected
        # from 11:40. Their separate next subjects therefore move to 12:40, and
        # the general English sitting waits for both branches until 13:40.
        self.assertNotIn(literature.id, impacts)
        self.assertEqual(
            impacts[physics.id].suggested_start_at,
            self.checked_at + timedelta(hours=1),
        )
        self.assertEqual(
            impacts[government.id].suggested_start_at,
            self.checked_at + timedelta(hours=1),
        )
        self.assertEqual(
            impacts[english.id].suggested_start_at,
            self.checked_at + timedelta(hours=2),
        )
        self.assertIn("schedule_reschedule_required", preflight.blockers)
        self.assertFalse(preflight.can_activate)

    async def test_active_exam_past_projected_finish_has_unknown_end_until_closed(self):
        source = self.exam(
            title="Chemistry",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at - timedelta(minutes=40),
        )
        active = self.exam(
            title="Earlier Science Sitting",
            status=ExamStatus.ACTIVE,
            scheduled_start_at=self.checked_at - timedelta(hours=2),
            activated_at=self.checked_at - timedelta(hours=2),
        )
        physics = self.exam(
            title="Physics",
            status=ExamStatus.SEALED,
            scheduled_start_at=self.checked_at + timedelta(minutes=20),
        )
        scopes = {
            source.id: frozenset({self.science_class}),
            active.id: frozenset({self.science_class}),
            physics.id: frozenset({self.science_class}),
        }

        with patch.object(
            ExamTimetableService,
            "_suspension_state",
            new=AsyncMock(return_value=({active.id: timedelta(0)}, set())),
        ):
            preflight = await self.run_preflight(
                source=source,
                rows=[active, physics],
                scopes=scopes,
                buffered=False,
            )

        impact = next(
            row for row in preflight.affected_exams if row.exam_id == physics.id
        )
        self.assertIsNone(impact.suggested_start_at)
        self.assertIsNone(impact.suggested_end_at)
        self.assertIn("no reliable finish time", impact.reason)
        self.assertIn(active.id, impact.blocked_by_exam_ids)
        self.assertFalse(preflight.can_activate)


class ActivationServiceGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_require_activation_clear_never_applies_suggestion_buffer(self):
        now = datetime.now(UTC)
        clean = ActivationPreflight(
            exam_id=uuid4(),
            checked_at=now,
            scheduled_start_at=now - timedelta(minutes=10),
            proposed_activation_at=now,
            projected_end_at=now + timedelta(hours=1),
            delay_seconds=600,
            can_activate=True,
            blockers=(),
            conflicting_operational_exam_ids=(),
            affected_exams=(),
        )
        db = AsyncMock()

        with patch.object(
            ExamTimetableService,
            "activation_preflight",
            new=AsyncMock(return_value=clean),
        ) as preflight:
            await ExamTimetableService.require_activation_clear(
                db,
                exam_id=clean.exam_id,
                proposed_activation_at=now,
            )

        self.assertFalse(preflight.await_args.kwargs["apply_recovery_buffer"])


if __name__ == "__main__":
    unittest.main()
