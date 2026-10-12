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

from app.domains.attempts.models import AttemptStatus
from app.domains.attempts.service import AttemptService


class AttemptTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_exam_wide_suspension_does_not_consume_candidate_time(self):
        started = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
        at = started + timedelta(minutes=30)
        attempt = SimpleNamespace(
            status=AttemptStatus.IN_PROGRESS,
            active_since=started,
            elapsed_seconds=0,
            time_limit_seconds=3600,
        )
        suspension = SimpleNamespace(
            suspended_at=started + timedelta(minutes=10),
            resumed_at=started + timedelta(minutes=20),
        )
        with patch(
            "app.domains.attempts.service.AttemptRuntimeRepository.list_exam_suspensions",
            AsyncMock(return_value=[suspension]),
        ):
            remaining = await AttemptService.remaining_seconds(
                AsyncMock(),
                attempt=attempt,
                exam_id=uuid4(),
                at=at,
            )

        self.assertEqual(remaining, 2400)

    async def test_interrupted_attempt_uses_only_checkpointed_elapsed_time(self):
        attempt = SimpleNamespace(
            status=AttemptStatus.INTERRUPTED,
            active_since=None,
            elapsed_seconds=900,
            time_limit_seconds=3600,
        )
        remaining = await AttemptService.remaining_seconds(
            AsyncMock(),
            attempt=attempt,
            exam_id=uuid4(),
        )
        self.assertEqual(remaining, 2700)


if __name__ == "__main__":
    unittest.main()
