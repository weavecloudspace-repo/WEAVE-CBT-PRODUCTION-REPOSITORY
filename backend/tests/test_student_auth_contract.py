from __future__ import annotations

import os
import unittest

from pydantic import ValidationError

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.core.database import Base
from app.domains.auth.student_models import StudentExamSession
from app.domains.auth.student_schemas import (
    StudentExamAvailability,
    StudentLoginRequest,
    StudentLoginResponse,
)


class StudentAuthContractTests(unittest.TestCase):
    def test_login_contract_uses_password_not_pin(self) -> None:
        payload = StudentLoginRequest.model_validate(
            {
                "admission_number": "STU/2026/001",
                "password": "stu/2026/001",
            }
        )
        self.assertEqual(payload.password, "stu/2026/001")

        with self.assertRaises(ValidationError):
            StudentLoginRequest.model_validate(
                {
                    "admission_number": "STU/2026/001",
                    "pin": "123456",
                }
            )

    def test_no_student_password_or_pin_verifier_is_stored(self) -> None:
        self.assertNotIn("student_cbt_credentials", Base.metadata.tables)

    def test_waiting_room_session_can_exist_before_exam_binding(self) -> None:
        candidate = StudentExamSession.__table__.c.candidate_id
        exam = StudentExamSession.__table__.c.exam_id
        self.assertTrue(candidate.nullable)
        self.assertTrue(exam.nullable)
        self.assertNotIn("password", StudentExamSession.__table__.c)
        self.assertNotIn("pin_hash", StudentExamSession.__table__.c)

    def test_no_exam_is_a_successful_login_availability_state(self) -> None:
        payload = StudentLoginResponse(
            student_id="77777777-7777-7777-7777-777777777777",
            candidate_id=None,
            exam_id=None,
            exam_title=None,
            display_name="Ada Okafor",
            availability=StudentExamAvailability.NO_EXAM,
            status_message="No examination is currently available for you.",
            is_makeup=False,
        )
        self.assertEqual(payload.availability, StudentExamAvailability.NO_EXAM.value)
        self.assertIsNone(payload.exam_id)
        self.assertIsNone(payload.candidate_id)


if __name__ == "__main__":
    unittest.main()
