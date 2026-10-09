from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["DEBUG"] = "false"

from app.domains.academics.repository import AcademicRepository
from app.domains.auth.student_schemas import StudentExamAvailability
from app.domains.auth.student_service import (
    StudentAuthService,
)
from app.domains.exams.models import ExamStatus
from app.domains.sync.invalidation import SyncInvalidationRepository


class RevisionRosterIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_student_candidate_lookup_only_considers_latest_revision(
        self,
    ) -> None:
        """A candidate row on a superseded SEALED revision must be invisible."""

        result = MagicMock()
        result.tuples.return_value.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        await StudentAuthService._normal_candidate_rows(
            db,
            student_id=uuid4(),
            statuses=(ExamStatus.SEALED,),
        )

        statement = db.execute.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()

        self.assertIn("revision_of_exam_id", sql)
        self.assertIn("exists", sql)
        self.assertIn("not", sql)
        self.assertIn("exam_candidates", sql)
        self.assertIn("sealed", sql)

    async def test_sync_invalidation_only_targets_latest_sealed_rosters(self) -> None:
        """Enrollment sync must never make a superseded roster stale again."""

        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        affected = await SyncInvalidationRepository.mark_pre_execution_rosters_stale(db)

        self.assertEqual(affected, 0)
        self.assertEqual(db.execute.await_count, 1)
        statement = db.execute.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()

        self.assertIn("revision_of_exam_id", sql)
        self.assertIn("exists", sql)
        self.assertIn("not", sql)
        self.assertIn("sealed", sql)
        self.assertIn("ready", sql)

    async def test_new_student_is_not_given_superseded_waiting_exam(self) -> None:
        """Regression for enrollment after a newer revision has begun execution.

        The SQL lookup above removes superseded candidate rows. With no candidate
        on the current revision, normal ACTIVE/SUSPENDED/SEALED resolution must
        therefore fall through to NO_EXAM instead of WAITING_FOR_ACTIVATION.
        """

        enrollment = SimpleNamespace(student_id=uuid4())
        candidate_rows = AsyncMock(side_effect=[[], [], []])
        db = AsyncMock()

        with (
            patch.object(StudentAuthService, "_normal_candidate_rows", candidate_rows),
            patch.object(
                AcademicRepository,
                "get_current_session",
                AsyncMock(return_value=None),
            ),
        ):
            resolution = await StudentAuthService._resolve_candidate(
                db,
                enrollment=enrollment,
            )

        self.assertEqual(resolution.availability, StudentExamAvailability.NO_EXAM)
        self.assertIsNone(resolution.candidate)
        self.assertIsNone(resolution.exam)
        self.assertEqual(candidate_rows.await_count, 3)
        self.assertEqual(
            [call.kwargs["statuses"] for call in candidate_rows.await_args_list],
            [
                (ExamStatus.ACTIVE,),
                (ExamStatus.SUSPENDED,),
                (ExamStatus.SEALED,),
            ],
        )

    async def test_current_sealed_revision_still_resolves_waiting_room(self) -> None:
        """The fix must not remove legitimate pre-execution waiting-room access."""

        student_id = uuid4()
        exam_id = uuid4()
        enrollment = SimpleNamespace(student_id=student_id)
        candidate = SimpleNamespace(
            id=uuid4(),
            student_id=student_id,
            exam_id=exam_id,
        )
        exam = SimpleNamespace(id=exam_id)
        candidate_rows = AsyncMock(side_effect=[[], [], [(candidate, exam)]])
        db = AsyncMock()

        with patch.object(
            StudentAuthService,
            "_normal_candidate_rows",
            candidate_rows,
        ):
            resolution = await StudentAuthService._resolve_candidate(
                db,
                enrollment=enrollment,
            )

        self.assertEqual(
            resolution.availability,
            StudentExamAvailability.WAITING_FOR_ACTIVATION,
        )
        self.assertIs(resolution.candidate, candidate)
        self.assertIs(resolution.exam, exam)


if __name__ == "__main__":
    unittest.main()
