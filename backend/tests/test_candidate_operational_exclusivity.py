import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.candidates.models import CandidateStatus
from app.domains.candidates.service import CandidateService
from app.domains.exams.models import ExamStatus
from app.domains.exams.timetable_service import ExamTimetableService


class CandidateOperationalExclusivityTests(unittest.IsolatedAsyncioTestCase):
    def candidate(self):
        return SimpleNamespace(
            id=uuid4(),
            student_id=uuid4(),
            exam_id=uuid4(),
            status=CandidateStatus.BLOCKED,
            status_reason="manual block",
        )

    def exam(self, *, status):
        return SimpleNamespace(
            id=uuid4(),
            status=status,
            session_id=uuid4(),
            term_id=uuid4(),
            curriculum_subject_id=uuid4(),
        )

    async def test_unblocking_active_exam_rejects_student_busy_elsewhere(self):
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=True)
        candidate = self.candidate()
        exam = self.exam(status=ExamStatus.ACTIVE)
        candidate.exam_id = exam.id

        with self.assertRaisesRegex(
            ValueError,
            "already assigned to another operational examination",
        ):
            await CandidateService._require_operational_unblock_safe(
                db,
                candidate=candidate,
                exam=exam,
            )

        db.scalar.assert_awaited_once()
        self.assertIn("EXISTS", str(db.scalar.await_args.args[0]).upper())

    async def test_unblocking_suspended_exam_is_checked_too(self):
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=False)
        candidate = self.candidate()
        exam = self.exam(status=ExamStatus.SUSPENDED)
        candidate.exam_id = exam.id

        await CandidateService._require_operational_unblock_safe(
            db,
            candidate=candidate,
            exam=exam,
        )

        db.scalar.assert_awaited_once()

    async def test_unblocking_sealed_exam_defers_conflict_check_until_activation(self):
        db = AsyncMock()
        db.scalar = AsyncMock()
        candidate = self.candidate()
        exam = self.exam(status=ExamStatus.SEALED)
        candidate.exam_id = exam.id

        await CandidateService._require_operational_unblock_safe(
            db,
            candidate=candidate,
            exam=exam,
        )

        db.scalar.assert_not_awaited()

    async def test_unblock_acquires_advisory_locks_before_candidate_and_exam_row_locks(
        self,
    ):
        db = AsyncMock()
        candidate = self.candidate()
        exam = self.exam(status=ExamStatus.ACTIVE)
        candidate.exam_id = exam.id
        actor = SimpleNamespace(is_active=True, role="admin")
        level_id = uuid4()
        events: list[str] = []

        async def get_candidate_and_exam(_cls, _db, **kwargs):
            if kwargs.get("lock_candidate") or kwargs.get("lock_exam"):
                events.append("row_locks")
            else:
                events.append("preview")
            return candidate, exam

        async def acquire_level_lock(_db, **_kwargs):
            events.append("level_lock")

        async def acquire_candidate_lock(_db):
            events.append("candidate_lock")

        with (
            patch.object(
                CandidateService,
                "_get_candidate_and_exam",
                new=classmethod(get_candidate_and_exam),
            ),
            patch.object(
                ExamTimetableService,
                "level_id",
                new=AsyncMock(return_value=level_id),
            ),
            patch.object(
                ExamTimetableService,
                "acquire_level_lock",
                new=AsyncMock(side_effect=acquire_level_lock),
            ) as acquire_lock,
            patch.object(
                ExamTimetableService,
                "acquire_operational_candidate_lock",
                new=AsyncMock(side_effect=acquire_candidate_lock),
            ) as acquire_candidate_scope_lock,
            patch.object(
                CandidateService,
                "_require_operational_unblock_safe",
                new=AsyncMock(),
            ) as safety_check,
            patch(
                "app.domains.candidates.service.CandidateRepository.save_candidate",
                new=AsyncMock(side_effect=lambda _db, value: value),
            ),
            patch(
                "app.domains.candidates.service.CandidateResponse.model_validate",
                return_value="ok",
            ),
        ):
            response = await CandidateService.unblock_candidate(
                db,
                actor=actor,
                candidate_id=candidate.id,
            )

        self.assertEqual(response, "ok")
        self.assertEqual(
            events,
            ["preview", "level_lock", "candidate_lock", "row_locks"],
        )
        acquire_lock.assert_awaited_once_with(
            db,
            session_id=exam.session_id,
            term_id=exam.term_id,
            level_id=level_id,
        )
        acquire_candidate_scope_lock.assert_awaited_once_with(db)
        safety_check.assert_awaited_once_with(
            db,
            candidate=candidate,
            exam=exam,
        )
        self.assertEqual(candidate.status, CandidateStatus.ELIGIBLE)
        db.commit.assert_awaited_once()

    def test_candidate_mutation_is_frozen_during_closing(self):
        with self.assertRaisesRegex(ValueError, "Finalizing"):
            CandidateService._ensure_exam_mutable(ExamStatus.CLOSING)

    def test_candidate_mutation_is_frozen_during_cancelling(self):
        with self.assertRaisesRegex(ValueError, "Finalizing"):
            CandidateService._ensure_exam_mutable(ExamStatus.CANCELLING)


if __name__ == "__main__":
    unittest.main()
