# ruff: noqa: E402

import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.academics.repository import AcademicRepository
from app.domains.attempts.guarded_service import AttemptService
from app.domains.attempts.models import AttemptEndReason, AttemptStatus
from app.domains.attempts.repository import AttemptRepository
from app.domains.auth.student_lifecycle_service import (
    COMPLETED_MESSAGE,
    StudentAuthService,
)
from app.domains.auth.student_schemas import StudentExamAvailability
from app.domains.auth.student_service import (
    NO_EXAM_MESSAGE,
    StudentAuthenticationError,
    StudentSessionContext,
)
from app.domains.exams.models import ExamStatus
from app.domains.results.repository import ResultRepository


class StudentCompletedAttemptResolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.student_id = uuid4()
        self.enrollment = SimpleNamespace(student_id=self.student_id)

    def row(self, status: ExamStatus, title: str = "JSS1 English Exam"):
        exam_id = uuid4()
        candidate = SimpleNamespace(
            id=uuid4(),
            student_id=self.student_id,
            exam_id=exam_id,
        )
        exam = SimpleNamespace(
            id=exam_id,
            title=title,
            status=status,
            scheduled_start_at=datetime.now(UTC),
            activated_at=datetime.now(UTC),
        )
        return candidate, exam

    async def resolve_rows(self, rows, attempt_status_by_candidate):
        async def get_attempt(_db, candidate_id):
            status = attempt_status_by_candidate.get(candidate_id)
            return None if status is None else SimpleNamespace(status=status)

        db = AsyncMock()
        with (
            patch.object(
                StudentAuthService,
                "_normal_candidate_rows",
                new=AsyncMock(return_value=rows),
            ) as candidate_rows,
            patch.object(
                AttemptRepository,
                "get_attempt_by_candidate_id",
                new=AsyncMock(side_effect=get_attempt),
            ) as get_attempt,
        ):
            resolution = await StudentAuthService._resolve_candidate(
                db,
                enrollment=self.enrollment,
            )
        return resolution, candidate_rows, get_attempt

    async def test_unfinished_attempt_is_reported_for_resume_after_suspension(self) -> None:
        for status in (AttemptStatus.IN_PROGRESS, AttemptStatus.INTERRUPTED):
            with self.subTest(attempt_status=status):
                candidate, exam = self.row(ExamStatus.SUSPENDED)
                suspended, _, _ = await self.resolve_rows(
                    [(candidate, exam)], {candidate.id: status}
                )
                self.assertTrue(suspended.has_unfinished_attempt)
                self.assertEqual(suspended.availability, StudentExamAvailability.SUSPENDED)

                exam.status = ExamStatus.ACTIVE
                resumed, _, _ = await self.resolve_rows(
                    [(candidate, exam)], {candidate.id: status}
                )
                self.assertTrue(resumed.has_unfinished_attempt)
                self.assertEqual(resumed.availability, StudentExamAvailability.READY)
                self.assertIn("ready to resume", resumed.status_message)
                candidate.display_name = "Ada"
                response = StudentAuthService._build_response(
                    enrollment=self.enrollment, resolution=resumed
                )
                self.assertTrue(response.model_dump()["has_unfinished_attempt"])

    async def test_unstarted_exam_does_not_offer_resume_after_suspension(self) -> None:
        candidate, exam = self.row(ExamStatus.SUSPENDED)
        suspended, _, _ = await self.resolve_rows([(candidate, exam)], {})
        self.assertFalse(suspended.has_unfinished_attempt)
        exam.status = ExamStatus.ACTIVE
        ready, _, _ = await self.resolve_rows([(candidate, exam)], {})
        self.assertFalse(ready.has_unfinished_attempt)
        self.assertEqual(ready.availability, StudentExamAvailability.READY)
        self.assertNotIn("resume", ready.status_message)

    async def test_submitted_active_exam_resolves_directly_to_completed(self) -> None:
        candidate, exam = self.row(ExamStatus.ACTIVE)
        resolution, candidate_rows, get_attempt = await self.resolve_rows(
            [(candidate, exam)],
            {candidate.id: AttemptStatus.SUBMITTED},
        )

        self.assertEqual(
            resolution.availability,
            StudentExamAvailability.COMPLETED,
        )
        self.assertEqual(resolution.status_message, COMPLETED_MESSAGE)
        self.assertFalse(resolution.has_unfinished_attempt)
        self.assertIs(resolution.candidate, candidate)
        self.assertIs(resolution.exam, exam)
        self.assertEqual(
            candidate_rows.await_args.kwargs["statuses"],
            (ExamStatus.ACTIVE, ExamStatus.SUSPENDED),
        )
        get_attempt.assert_awaited_once_with(ANY, candidate.id)

    async def test_submitted_suspended_exam_hides_suspension_and_resolves_completed(
        self,
    ) -> None:
        candidate, exam = self.row(ExamStatus.SUSPENDED)
        resolution, _candidate_rows, _get_attempt = await self.resolve_rows(
            [(candidate, exam)],
            {candidate.id: AttemptStatus.SUBMITTED},
        )

        self.assertEqual(
            resolution.availability,
            StudentExamAvailability.COMPLETED,
        )
        self.assertEqual(resolution.status_message, COMPLETED_MESSAGE)
        self.assertNotEqual(
            resolution.availability,
            StudentExamAvailability.SUSPENDED,
        )

    async def test_in_progress_suspended_exam_still_uses_suspension_waiting_room(
        self,
    ) -> None:
        candidate, exam = self.row(ExamStatus.SUSPENDED)
        resolution, _candidate_rows, _get_attempt = await self.resolve_rows(
            [(candidate, exam)],
            {candidate.id: AttemptStatus.IN_PROGRESS},
        )

        self.assertEqual(
            resolution.availability,
            StudentExamAvailability.SUSPENDED,
        )
        self.assertIn("temporarily paused", resolution.status_message)
        self.assertIs(resolution.exam, exam)

    async def test_unstarted_active_exam_wins_over_another_completed_live_exam(
        self,
    ) -> None:
        completed_candidate, completed_exam = self.row(
            ExamStatus.ACTIVE,
            "English",
        )
        pending_candidate, pending_exam = self.row(
            ExamStatus.ACTIVE,
            "French",
        )

        resolution, _candidate_rows, _get_attempt = await self.resolve_rows(
            [
                (completed_candidate, completed_exam),
                (pending_candidate, pending_exam),
            ],
            {
                completed_candidate.id: AttemptStatus.SUBMITTED,
                pending_candidate.id: None,
            },
        )

        self.assertEqual(resolution.availability, StudentExamAvailability.READY)
        self.assertIs(resolution.candidate, pending_candidate)
        self.assertIs(resolution.exam, pending_exam)

    async def test_unfinished_suspended_exam_wins_over_completed_active_exam(
        self,
    ) -> None:
        completed_candidate, completed_exam = self.row(
            ExamStatus.ACTIVE,
            "English",
        )
        suspended_candidate, suspended_exam = self.row(
            ExamStatus.SUSPENDED,
            "French",
        )

        resolution, _candidate_rows, _get_attempt = await self.resolve_rows(
            [
                (completed_candidate, completed_exam),
                (suspended_candidate, suspended_exam),
            ],
            {
                completed_candidate.id: AttemptStatus.SUBMITTED,
                suspended_candidate.id: AttemptStatus.INTERRUPTED,
            },
        )

        self.assertEqual(
            resolution.availability,
            StudentExamAvailability.SUSPENDED,
        )
        self.assertIs(resolution.candidate, suspended_candidate)
        self.assertIs(resolution.exam, suspended_exam)

    async def test_two_completed_live_exams_resolve_to_no_exam_instead_of_random_score(
        self,
    ) -> None:
        first_candidate, first_exam = self.row(ExamStatus.ACTIVE, "English")
        second_candidate, second_exam = self.row(ExamStatus.SUSPENDED, "French")

        resolution, _candidate_rows, _get_attempt = await self.resolve_rows(
            [(first_candidate, first_exam), (second_candidate, second_exam)],
            {
                first_candidate.id: AttemptStatus.SUBMITTED,
                second_candidate.id: AttemptStatus.SUBMITTED,
            },
        )

        self.assertEqual(
            resolution.availability,
            StudentExamAvailability.NO_EXAM,
        )
        self.assertEqual(resolution.status_message, NO_EXAM_MESSAGE)
        self.assertIsNone(resolution.candidate)
        self.assertIsNone(resolution.exam)

    async def test_two_unfinished_live_exams_are_rejected_as_ambiguous(self) -> None:
        first_candidate, first_exam = self.row(ExamStatus.ACTIVE, "English")
        second_candidate, second_exam = self.row(ExamStatus.SUSPENDED, "French")
        db = AsyncMock()

        async def get_attempt(_db, candidate_id):
            if candidate_id == first_candidate.id:
                return None
            return SimpleNamespace(status=AttemptStatus.IN_PROGRESS)

        with (
            patch.object(
                StudentAuthService,
                "_normal_candidate_rows",
                new=AsyncMock(
                    return_value=[
                        (first_candidate, first_exam),
                        (second_candidate, second_exam),
                    ]
                ),
            ),
            patch.object(
                AttemptRepository,
                "get_attempt_by_candidate_id",
                new=AsyncMock(side_effect=get_attempt),
            ),
            self.assertRaisesRegex(
                StudentAuthenticationError,
                "Multiple unfinished live examinations",
            ),
        ):
            await StudentAuthService._resolve_candidate(
                db,
                enrollment=self.enrollment,
            )

    async def test_terminated_live_attempt_is_not_offered_as_a_fresh_exam(self) -> None:
        candidate, exam = self.row(ExamStatus.ACTIVE)
        resolution, _candidate_rows, _get_attempt = await self.resolve_rows(
            [(candidate, exam)],
            {candidate.id: AttemptStatus.TERMINATED},
        )

        self.assertEqual(
            resolution.availability,
            StudentExamAvailability.NO_EXAM,
        )
        self.assertIsNone(resolution.candidate)
        self.assertIsNone(resolution.exam)


class StudentCompletedResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_result_returns_exact_submitted_attempt_score(self) -> None:
        attempt_id = uuid4()
        candidate_id = uuid4()
        exam_id = uuid4()
        result_id = uuid4()
        ended_at = datetime.now(UTC)
        attempt = SimpleNamespace(
            id=attempt_id,
            status=AttemptStatus.SUBMITTED,
            end_reason=AttemptEndReason.CANDIDATE_SUBMITTED,
            ended_at=ended_at,
        )
        candidate = SimpleNamespace(id=candidate_id)
        curriculum_subject_id = uuid4()
        subject_id = uuid4()
        exam = SimpleNamespace(id=exam_id, curriculum_subject_id=curriculum_subject_id)
        result = SimpleNamespace(
            voided_at=None,
            id=result_id,
            raw_score=8,
            raw_max_score=10,
            percentage="80.00",
            component_score="16.00",
            component_maximum_score="20.00",
        )
        context = StudentSessionContext(
            session_id=uuid4(),
            student_id=uuid4(),
            candidate_id=candidate_id,
            exam_id=exam_id,
            makeup_authorization_id=None,
        )
        db = AsyncMock()

        with (
            patch.object(
                AttemptService,
                "_get_current_attempt",
                new=AsyncMock(return_value=(attempt, candidate, exam)),
            ),
            patch.object(
                ResultRepository,
                "get_result_by_attempt_id",
                new=AsyncMock(return_value=result),
            ) as get_result,
            patch.object(
                AcademicRepository,
                "get_curriculum_subject_by_id",
                new=AsyncMock(return_value=SimpleNamespace(subject_id=subject_id)),
            ) as get_curriculum_subject,
            patch.object(
                AcademicRepository,
                "get_subject_by_id",
                new=AsyncMock(return_value=SimpleNamespace(name="Literature")),
            ) as get_subject,
        ):
            response = await AttemptService.get_current_result(db, context=context)

        self.assertEqual(response.attempt_id, attempt_id)
        self.assertEqual(response.result_id, result_id)
        self.assertEqual(response.subject_name, "Literature")
        get_curriculum_subject.assert_awaited_once_with(db, curriculum_subject_id)
        get_subject.assert_awaited_once_with(db, subject_id)
        self.assertEqual(response.status, AttemptStatus.SUBMITTED.value)
        self.assertEqual(response.raw_score, 8)
        self.assertEqual(response.raw_max_score, 10)
        self.assertEqual(response.percentage, "80.00")
        self.assertEqual(response.component_score, "16.00")
        self.assertEqual(response.component_maximum_score, "20.00")
        get_result.assert_awaited_once_with(db, attempt_id)

    async def test_current_result_rejects_non_submitted_attempt(self) -> None:
        attempt = SimpleNamespace(
            id=uuid4(),
            status=AttemptStatus.IN_PROGRESS,
        )
        context = StudentSessionContext(
            session_id=uuid4(),
            student_id=uuid4(),
            candidate_id=uuid4(),
            exam_id=uuid4(),
            makeup_authorization_id=None,
        )
        db = AsyncMock()

        with (
            patch.object(
                AttemptService,
                "_get_current_attempt",
                new=AsyncMock(
                    return_value=(attempt, SimpleNamespace(), SimpleNamespace())
                ),
            ),
            self.assertRaisesRegex(ValueError, "not completed"),
        ):
            await AttemptService.get_current_result(db, context=context)


if __name__ == "__main__":
    unittest.main()
