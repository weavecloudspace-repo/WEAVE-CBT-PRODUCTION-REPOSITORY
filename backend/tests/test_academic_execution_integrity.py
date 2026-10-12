from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.academics.repository import AcademicRepository
from app.domains.candidates.models import CandidateStatus
from app.domains.candidates.repository import CandidateRepository
from app.domains.candidates.service import CandidateService
from app.domains.exams.models import ExamRosterStatus, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.sync.repository import SyncRepository


def enrollment(*, student_id=None, class_id=None, session_id=None, admission="STD-001"):
    return SimpleNamespace(
        id=uuid4(),
        student_id=student_id or uuid4(),
        admission_number=admission,
        first_name="Ada",
        last_name="Lovelace",
        academic_level_id=uuid4(),
        class_id=class_id or uuid4(),
        academic_session_id=session_id or uuid4(),
        is_current=True,
        student_status="active",
    )


def sealed_exam(**overrides):
    values = {
        "id": uuid4(),
        "session_id": uuid4(),
        "curriculum_subject_id": uuid4(),
        "status": ExamStatus.SEALED,
        "roster_status": ExamRosterStatus.PENDING,
        "roster_version": 0,
        "roster_candidate_count": 0,
        "roster_prepared_at": None,
        "roster_error": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class CandidateAcademicIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_roster_uses_frozen_classes_and_exam_session(self) -> None:
        db = AsyncMock()
        current_exam = sealed_exam()
        class_a = uuid4()
        class_b = uuid4()
        target_classes = [
            SimpleNamespace(class_id=class_a),
            SimpleNamespace(class_id=class_b),
        ]
        first = enrollment(class_id=class_a, session_id=current_exam.session_id)
        second = enrollment(
            class_id=class_b,
            session_id=current_exam.session_id,
            admission="STD-002",
        )

        async def add_candidates(_db, rows):
            rows = list(rows)
            now = datetime.now(UTC)
            for row in rows:
                row.id = uuid4()
                row.created_at = now
                row.updated_at = now
            return rows

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
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                SyncRepository,
                "acquire_apply_lock",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "list_target_classes_for_exam",
                new=AsyncMock(return_value=target_classes),
            ),
            patch.object(
                AcademicRepository,
                "list_current_enrollments_for_classes",
                new=AsyncMock(return_value=[first, second]),
            ) as list_enrollments,
            patch.object(
                CandidateRepository,
                "add_candidates",
                new=AsyncMock(side_effect=add_candidates),
            ) as add_rows,
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            result = await CandidateService.prepare_roster(
                db,
                exam_id=current_exam.id,
            )

        list_enrollments.assert_awaited_once_with(
            db,
            [class_a, class_b],
            academic_session_id=current_exam.session_id,
        )
        added = add_rows.await_args.args[1]
        self.assertEqual(
            {row.student_id for row in added}, {first.student_id, second.student_id}
        )
        self.assertEqual({row.class_id for row in added}, {class_a, class_b})
        self.assertEqual(result.roster_status, ExamRosterStatus.READY)
        self.assertEqual(result.roster_candidate_count, 2)
        self.assertEqual(result.roster_version, 1)
        db.commit.assert_awaited_once()

    async def test_reconcile_withdraws_student_no_longer_in_frozen_classes(
        self,
    ) -> None:
        db = AsyncMock()
        current_exam = sealed_exam(
            roster_status=ExamRosterStatus.STALE,
            roster_version=2,
            roster_candidate_count=2,
        )
        class_id = uuid4()
        remaining_enrollment = enrollment(
            class_id=class_id,
            session_id=current_exam.session_id,
        )
        leaving_student_id = uuid4()
        existing_remaining = SimpleNamespace(
            id=uuid4(),
            exam_id=current_exam.id,
            enrollment_id=remaining_enrollment.id,
            student_id=remaining_enrollment.student_id,
            class_id=class_id,
            admission_number=remaining_enrollment.admission_number,
            display_name="Ada Lovelace",
            status=CandidateStatus.ELIGIBLE,
            status_reason=None,
            roster_version=2,
        )
        existing_leaving = SimpleNamespace(
            id=uuid4(),
            exam_id=current_exam.id,
            enrollment_id=uuid4(),
            student_id=leaving_student_id,
            class_id=class_id,
            admission_number="STD-009",
            display_name="Old Student",
            status=CandidateStatus.ELIGIBLE,
            status_reason=None,
            roster_version=2,
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
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                SyncRepository,
                "acquire_apply_lock",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "list_target_classes_for_exam",
                new=AsyncMock(return_value=[SimpleNamespace(class_id=class_id)]),
            ),
            patch.object(
                AcademicRepository,
                "list_current_enrollments_for_classes",
                new=AsyncMock(return_value=[remaining_enrollment]),
            ),
            patch.object(
                CandidateRepository,
                "list_candidates_for_exam",
                new=AsyncMock(return_value=[existing_remaining, existing_leaving]),
            ),
            patch.object(
                CandidateRepository,
                "save_candidates",
                new=AsyncMock(),
            ) as save_candidates,
            patch.object(
                CandidateRepository,
                "add_candidates",
                new=AsyncMock(),
            ) as add_candidates,
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            result = await CandidateService.reconcile_roster(
                db,
                exam_id=current_exam.id,
            )

        add_candidates.assert_not_awaited()
        changed = save_candidates.await_args.args[1]
        self.assertIn(existing_leaving, changed)
        self.assertEqual(existing_leaving.status, CandidateStatus.WITHDRAWN)
        self.assertIn("no longer academically eligible", existing_leaving.status_reason)
        self.assertEqual(existing_remaining.status, CandidateStatus.ELIGIBLE)
        self.assertEqual(result.roster_status, ExamRosterStatus.READY)
        self.assertEqual(result.roster_candidate_count, 1)
        self.assertEqual(result.roster_version, 3)


if __name__ == "__main__":
    unittest.main()
