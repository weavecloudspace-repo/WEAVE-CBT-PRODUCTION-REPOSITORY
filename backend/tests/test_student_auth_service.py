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

from app.domains.auth.student_repository import StudentAuthRepository
from app.domains.auth.student_schemas import StudentExamAvailability
from app.domains.auth.student_service import (
    INVALID_STUDENT_LOGIN,
    NO_EXAM_MESSAGE,
    READY_MESSAGE,
    SUSPENDED_MESSAGE,
    StudentAuthenticationError,
    StudentAuthService,
    StudentExamResolution,
    hash_student_session_token,
)
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.models import ExamStatus


class StudentAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_uses_uppercase_admission_and_lowercase_admission_password(
        self,
    ):
        student_id = uuid4()
        candidate_id = uuid4()
        exam_id = uuid4()
        enrollment = SimpleNamespace(
            student_id=student_id,
            admission_number="STU/2026/001",
            first_name="Candidate",
            last_name="A",
        )
        candidate = SimpleNamespace(
            id=candidate_id,
            student_id=student_id,
            exam_id=exam_id,
            display_name="Candidate A",
        )
        exam = SimpleNamespace(
            id=exam_id,
            title="Mathematics",
            scheduled_start_at=None,
            activated_at=None,
        )
        old_session = SimpleNamespace(revoked_at=None, revocation_reason=None)
        captured = {}

        async def add_session(_db, session):
            captured["session"] = session
            return session

        db = AsyncMock()
        with (
            patch.object(
                StudentAuthService,
                "_get_current_enrollment",
                AsyncMock(return_value=enrollment),
            ),
            patch.object(
                StudentAuthService,
                "_resolve_candidate",
                AsyncMock(
                    return_value=StudentExamResolution(
                        candidate=candidate,
                        exam=exam,
                        makeup_authorization_id=None,
                        availability=StudentExamAvailability.READY,
                        status_message=READY_MESSAGE,
                    )
                ),
            ),
            patch.object(
                StudentAuthRepository,
                "list_unrevoked_sessions_for_student",
                AsyncMock(return_value=[old_session]),
            ),
            patch.object(
                StudentAuthRepository,
                "save_sessions",
                AsyncMock(return_value=[old_session]),
            ),
            patch.object(
                StudentAuthRepository,
                "add_session",
                AsyncMock(side_effect=add_session),
            ),
        ):
            result = await StudentAuthService.login(
                db,
                admission_number="STU/2026/001",
                password="stu/2026/001",
            )

        session = captured["session"]
        self.assertEqual(result.response.student_id, student_id)
        self.assertEqual(result.response.candidate_id, candidate_id)
        self.assertEqual(result.response.exam_id, exam_id)
        self.assertEqual(
            result.response.availability, StudentExamAvailability.READY.value
        )
        self.assertFalse(result.response.is_makeup)
        self.assertEqual(session.student_id, student_id)
        self.assertEqual(session.candidate_id, candidate_id)
        self.assertEqual(session.exam_id, exam_id)
        self.assertNotEqual(result.raw_token, session.token_hash)
        self.assertEqual(
            session.token_hash, hash_student_session_token(result.raw_token)
        )
        self.assertEqual(len(session.token_hash), 64)
        self.assertIsNotNone(old_session.revoked_at)
        self.assertEqual(
            old_session.revocation_reason,
            "Superseded by a new student login",
        )
        db.commit.assert_awaited_once()

    async def test_valid_student_can_login_without_available_exam(self):
        student_id = uuid4()
        enrollment = SimpleNamespace(
            student_id=student_id,
            admission_number="STU/2026/001",
            first_name="Ada",
            last_name="Okafor",
        )
        captured = {}

        async def add_session(_db, session):
            captured["session"] = session
            return session

        db = AsyncMock()
        with (
            patch.object(
                StudentAuthService,
                "_get_current_enrollment",
                AsyncMock(return_value=enrollment),
            ),
            patch.object(
                StudentAuthService,
                "_resolve_candidate",
                AsyncMock(
                    return_value=StudentExamResolution(
                        candidate=None,
                        exam=None,
                        makeup_authorization_id=None,
                        availability=StudentExamAvailability.NO_EXAM,
                        status_message=NO_EXAM_MESSAGE,
                    )
                ),
            ),
            patch.object(
                StudentAuthRepository,
                "list_unrevoked_sessions_for_student",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                StudentAuthRepository,
                "save_sessions",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                StudentAuthRepository,
                "add_session",
                AsyncMock(side_effect=add_session),
            ),
        ):
            result = await StudentAuthService.login(
                db,
                admission_number="STU/2026/001",
                password="stu/2026/001",
            )

        self.assertEqual(
            result.response.availability, StudentExamAvailability.NO_EXAM.value
        )
        self.assertEqual(result.response.status_message, NO_EXAM_MESSAGE)
        self.assertEqual(result.response.display_name, "Ada Okafor")
        self.assertIsNone(result.response.candidate_id)
        self.assertIsNone(result.response.exam_id)
        self.assertIsNone(captured["session"].candidate_id)
        self.assertIsNone(captured["session"].exam_id)
        db.commit.assert_awaited_once()

    async def test_suspended_exam_resolves_to_suspended_waiting_room_state(self):
        student_id = uuid4()
        exam_id = uuid4()
        enrollment = SimpleNamespace(student_id=student_id)
        candidate = SimpleNamespace(
            id=uuid4(),
            student_id=student_id,
            exam_id=exam_id,
        )
        exam = SimpleNamespace(
            id=exam_id,
            title="English",
            scheduled_start_at=None,
            activated_at=datetime.now(UTC),
        )
        rows = AsyncMock(side_effect=[[], [(candidate, exam)]])
        db = AsyncMock()

        with patch.object(StudentAuthService, "_normal_candidate_rows", rows):
            resolution = await StudentAuthService._resolve_candidate(
                db,
                enrollment=enrollment,
            )

        self.assertEqual(
            resolution.availability,
            StudentExamAvailability.SUSPENDED,
        )
        self.assertEqual(resolution.status_message, SUSPENDED_MESSAGE)
        self.assertIs(resolution.candidate, candidate)
        self.assertIs(resolution.exam, exam)
        self.assertEqual(rows.await_count, 2)
        self.assertEqual(
            rows.await_args_list[0].kwargs["statuses"],
            (ExamStatus.ACTIVE,),
        )
        self.assertEqual(
            rows.await_args_list[1].kwargs["statuses"],
            (ExamStatus.SUSPENDED,),
        )

    async def test_lowercase_admission_number_is_rejected_before_lookup(self):
        db = AsyncMock()
        lookup = AsyncMock()
        with (
            patch.object(StudentAuthService, "_get_current_enrollment", lookup),
            self.assertRaisesRegex(StudentAuthenticationError, INVALID_STUDENT_LOGIN),
        ):
            await StudentAuthService.login(
                db,
                admission_number="stu/2026/001",
                password="stu/2026/001",
            )

        lookup.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_password_must_be_lowercase_authoritative_admission_number(self):
        enrollment = SimpleNamespace(
            student_id=uuid4(),
            admission_number="STU/2026/001",
        )
        db = AsyncMock()

        with (
            patch.object(
                StudentAuthService,
                "_get_current_enrollment",
                AsyncMock(return_value=enrollment),
            ),
            self.assertRaisesRegex(StudentAuthenticationError, INVALID_STUDENT_LOGIN),
        ):
            await StudentAuthService.login(
                db,
                admission_number="STU/2026/001",
                password="STU/2026/001",
            )

        db.commit.assert_not_awaited()

    async def test_password_is_derived_from_stored_identity_not_other_submitted_value(
        self,
    ):
        with self.assertRaisesRegex(StudentAuthenticationError, INVALID_STUDENT_LOGIN):
            StudentAuthService._verify_admission_password(
                submitted_admission_number="STU/2026/001",
                submitted_password="stu/2026/999",
                stored_admission_number="STU/2026/001",
            )

    async def test_session_resolution_accepts_waiting_room_only_session(self):
        student_id = uuid4()
        session = SimpleNamespace(
            id=uuid4(),
            student_id=student_id,
            candidate_id=None,
            exam_id=None,
            makeup_authorization_id=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_seen_at=datetime.now(UTC),
            revoked_at=None,
        )
        db = AsyncMock()

        with patch.object(
            StudentAuthRepository,
            "get_session_by_hash",
            AsyncMock(return_value=session),
        ):
            context = await StudentAuthService.resolve_session(
                db,
                raw_token="opaque-token",
                touch=False,
            )

        self.assertEqual(context.student_id, student_id)
        self.assertIsNone(context.candidate_id)
        self.assertIsNone(context.exam_id)
        self.assertFalse(context.is_exam_bound)

    async def test_session_resolution_rejects_candidate_identity_mismatch(self):
        student_id = uuid4()
        candidate_id = uuid4()
        exam_id = uuid4()
        session = SimpleNamespace(
            id=uuid4(),
            student_id=student_id,
            candidate_id=candidate_id,
            exam_id=exam_id,
            makeup_authorization_id=None,
            token_hash="x" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_seen_at=datetime.now(UTC),
            revoked_at=None,
        )
        mismatched_candidate = SimpleNamespace(
            id=candidate_id,
            student_id=uuid4(),
            exam_id=exam_id,
        )
        db = AsyncMock()

        with (
            patch.object(
                StudentAuthRepository,
                "get_session_by_hash",
                AsyncMock(return_value=session),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                AsyncMock(return_value=mismatched_candidate),
            ),
            self.assertRaisesRegex(StudentAuthenticationError, "inconsistent"),
        ):
            await StudentAuthService.resolve_session(
                db,
                raw_token="opaque-token",
                touch=False,
            )

    async def test_session_resolution_returns_exact_bound_context(self):
        student_id = uuid4()
        candidate_id = uuid4()
        exam_id = uuid4()
        session = SimpleNamespace(
            id=uuid4(),
            student_id=student_id,
            candidate_id=candidate_id,
            exam_id=exam_id,
            makeup_authorization_id=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_seen_at=datetime.now(UTC),
            revoked_at=None,
        )
        candidate = SimpleNamespace(
            id=candidate_id,
            student_id=student_id,
            exam_id=exam_id,
        )
        db = AsyncMock()

        with (
            patch.object(
                StudentAuthRepository,
                "get_session_by_hash",
                AsyncMock(return_value=session),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                AsyncMock(return_value=candidate),
            ),
        ):
            context = await StudentAuthService.resolve_session(
                db,
                raw_token="opaque-token",
                touch=False,
            )

        self.assertEqual(context.student_id, student_id)
        self.assertEqual(context.candidate_id, candidate_id)
        self.assertEqual(context.exam_id, exam_id)
        self.assertTrue(context.is_exam_bound)


if __name__ == "__main__":
    unittest.main()
