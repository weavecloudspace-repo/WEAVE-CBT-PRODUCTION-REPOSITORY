import os
import unittest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.exams.models import Exam


class TimestampResponseContractTests(unittest.TestCase):
    def test_audit_timestamps_use_python_values_for_orm_mutations(self):
        created_at = Exam.__table__.c.created_at
        updated_at = Exam.__table__.c.updated_at

        self.assertIsNotNone(created_at.default)
        self.assertTrue(created_at.default.is_callable)
        self.assertIsNotNone(created_at.server_default)

        self.assertIsNotNone(updated_at.default)
        self.assertTrue(updated_at.default.is_callable)
        self.assertIsNotNone(updated_at.server_default)
        self.assertIsNotNone(updated_at.onupdate)
        self.assertTrue(updated_at.onupdate.is_callable)
        self.assertFalse(updated_at.onupdate.is_clause_element)


if __name__ == "__main__":
    unittest.main()
