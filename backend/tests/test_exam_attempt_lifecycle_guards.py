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

from app.domains.attempts.guarded_service import AttemptService
from app.domains.attempts.models import AttemptEndReason, AttemptStatus
from app.domains.candidates.lifecycle_service import CandidateService
from app.domains.candidates.models import CandidateStatus
from app.domains.exams.models import ExamStatus


class CandidateAttemptBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_block_rejects_candidate_after_attempt_exists(self):
        db = AsyncMock()
        actor = SimpleNamespace(id=uuid4())
        candidate_id = uuid4()
        candidate = SimpleNamespace(id=candidate_id)
        exam = SimpleNamespace(id=uuid4())

        with (
            patch.object(
                CandidateService,
                "_get_candidate_and_exam",
                AsyncMock(return_value=(candidate, exam)),
            ),
            patch.object(
                CandidateService,
                "_require_candidate_not_started",
                AsyncMock(
                    side_effect=ValueError(
                        "Candidate has already started this examination; use attempt controls instead"
                    )
                ),
            ),
            self.assertRaisesRegex(ValueError, "already started"),
        ):
            await CandidateService.block_candidate(
                db,
                actor=actor,
                candidate_id=candidate_id,
                reason="Not cleared",
            )

    async def test_late_start_rejects_candidate_after_attempt_exists(self):
        db = AsyncMock()
        actor = SimpleNamespace(id=uuid4())
        candidate_id = uuid4()
        candidate = SimpleNamespace(id=candidate_id, status=CandidateStatus.ELIGIBLE)
        exam = SimpleNamespace(id=uuid4(), status=ExamStatus.ACTIVE)

        with (
            patch.object(
                CandidateService,
                "_get_candidate_and_exam",
                AsyncMock(return_value=(candidate, exam)),
            ),
            patch.object(
                CandidateService,
                "_require_candidate_not_started",
                AsyncMock(
                    side_effect=ValueError(
                        "Candidate has already started this examination; use attempt controls instead"
                    )
                ),
            ),
            self.assertRaisesRegex(ValueError, "already started"),
        ):
            await CandidateService.grant_late_start(
                db,
                actor=actor,
                candidate_id=candidate_id,
                reason="Network delay",
            )

    async def test_null_latest_normal_start_means_zero_configured_grace(self):
        scheduled = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
        exam = SimpleNamespace(
            scheduled_start_at=scheduled,
            latest_normal_start_at=None,
            activated_at=None,
        )
        self.assertEqual(
            CandidateService._effective_late_start_deadline(exam),
            scheduled,
        )
        self.assertEqual(
            await AttemptService._effective_late_start_deadline(exam),
            scheduled,
        )

    async def test_delayed_activation_preserves_entry_grace(self):
        scheduled = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
        exam = SimpleNamespace(
            scheduled_start_at=scheduled,
            latest_normal_start_at=scheduled + timedelta(minutes=10),
            activated_at=scheduled + timedelta(minutes=4),
        )
        expected = scheduled + timedelta(minutes=14)
        self.assertEqual(
            CandidateService._effective_late_start_deadline(exam), expected
        )
        self.assertEqual(
            await AttemptService._effective_late_start_deadline(exam), expected
        )


class AttemptTimeoutFinalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_in_progress_attempt_is_submitted_with_time_expired(self):
        db = AsyncMock()
        attempt = SimpleNamespace(
            id=uuid4(),
            candidate_id=uuid4(),
            status=AttemptStatus.IN_PROGRESS,
        )
        candidate = SimpleNamespace(id=attempt.candidate_id, exam_id=uuid4())
        exam = SimpleNamespace(id=candidate.exam_id, status=ExamStatus.ACTIVE)

        with (
            patch(
                "app.domains.attempts.guarded_service.AttemptRepository.get_attempt_by_id",
                AsyncMock(return_value=attempt),
            ),
            patch(
                "app.domains.attempts.guarded_service.CandidateRepository.get_candidate_by_id",
                AsyncMock(return_value=candidate),
            ),
            patch(
                "app.domains.attempts.guarded_service.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch.object(
                AttemptService,
                "_is_makeup_candidate",
                AsyncMock(return_value=False),
            ),
            patch.object(
                AttemptService,
                "remaining_seconds",
                AsyncMock(return_value=0),
            ),
            patch.object(
                AttemptService,
                "_submit_locked",
                AsyncMock(),
            ) as submit_locked,
        ):
            affected_exam_id = await AttemptService.finalize_if_expired(
                db,
                attempt_id=attempt.id,
            )

        self.assertEqual(affected_exam_id, exam.id)
        submit_locked.assert_awaited_once()
        kwargs = submit_locked.await_args.kwargs
        self.assertEqual(kwargs["end_reason"], AttemptEndReason.TIME_EXPIRED)

    async def test_interrupted_attempt_is_never_timeout_finalized(self):
        db = AsyncMock()
        attempt = SimpleNamespace(
            id=uuid4(),
            status=AttemptStatus.INTERRUPTED,
        )
        with (
            patch(
                "app.domains.attempts.guarded_service.AttemptRepository.get_attempt_by_id",
                AsyncMock(return_value=attempt),
            ),
            patch.object(
                AttemptService,
                "_submit_locked",
                AsyncMock(),
            ) as submit_locked,
        ):
            affected_exam_id = await AttemptService.finalize_if_expired(
                db,
                attempt_id=attempt.id,
            )

        self.assertIsNone(affected_exam_id)
        submit_locked.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_suspension_protected_attempt_is_not_finalized_early(self):
        db = AsyncMock()
        attempt = SimpleNamespace(
            id=uuid4(),
            candidate_id=uuid4(),
            status=AttemptStatus.IN_PROGRESS,
        )
        candidate = SimpleNamespace(id=attempt.candidate_id, exam_id=uuid4())
        exam = SimpleNamespace(id=candidate.exam_id, status=ExamStatus.SUSPENDED)

        with (
            patch(
                "app.domains.attempts.guarded_service.AttemptRepository.get_attempt_by_id",
                AsyncMock(return_value=attempt),
            ),
            patch(
                "app.domains.attempts.guarded_service.CandidateRepository.get_candidate_by_id",
                AsyncMock(return_value=candidate),
            ),
            patch(
                "app.domains.attempts.guarded_service.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch.object(
                AttemptService,
                "_is_makeup_candidate",
                AsyncMock(return_value=False),
            ),
            patch.object(
                AttemptService,
                "remaining_seconds",
                AsyncMock(return_value=300),
            ),
            patch.object(
                AttemptService,
                "_submit_locked",
                AsyncMock(),
            ) as submit_locked,
        ):
            affected_exam_id = await AttemptService.finalize_if_expired(
                db,
                attempt_id=attempt.id,
            )

        self.assertIsNone(affected_exam_id)
        submit_locked.assert_not_awaited()
        db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
