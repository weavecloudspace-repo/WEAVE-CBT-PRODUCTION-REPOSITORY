import os
import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.auth.student_repository import StudentAuthRepository


class StudentSessionConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_locking_student_sessions_uses_advisory_lock_before_row_query(self):
        student_id = uuid4()
        advisory_result = MagicMock()
        sessions_result = MagicMock()
        sessions_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[advisory_result, sessions_result])

        sessions = await StudentAuthRepository.list_unrevoked_sessions_for_student(
            db,
            student_id,
            lock=True,
        )

        self.assertEqual(sessions, [])
        self.assertEqual(db.execute.await_count, 2)

        advisory_statement = str(db.execute.await_args_list[0].args[0])
        session_statement = str(db.execute.await_args_list[1].args[0])

        self.assertIn("pg_advisory_xact_lock", advisory_statement)
        self.assertIn("FOR UPDATE", session_statement.upper())


if __name__ == "__main__":
    unittest.main()
