import os
import unittest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.attempts.schemas import AttemptAnswerMutation
from app.domains.auth.student_schemas import StudentLoginRequest
from app.domains.exams.timetable_schemas import BatchExamStartRequest


class ExecutionSchemaTests(unittest.TestCase):
    def test_student_pin_must_be_numeric(self):
        with self.assertRaises(ValueError):
            StudentLoginRequest(admission_number="A1", pin="abcdef")

    def test_answer_option_ids_must_be_unique(self):
        from uuid import uuid4

        option_id = uuid4()
        with self.assertRaises(ValueError):
            AttemptAnswerMutation(
                mutation_sequence=1,
                selected_option_ids=[option_id, option_id],
            )

    def test_batch_exam_ids_must_be_unique(self):
        from uuid import uuid4

        exam_id = uuid4()
        with self.assertRaises(ValueError):
            BatchExamStartRequest(exam_ids=[exam_id, exam_id])


if __name__ == "__main__":
    unittest.main()
