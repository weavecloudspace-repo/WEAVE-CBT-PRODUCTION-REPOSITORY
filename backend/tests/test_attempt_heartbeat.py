from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["DEBUG"] = "false"

from app.domains.attempts.guarded_service import AttemptService
from app.domains.attempts.models import AttemptStatus
from app.domains.attempts.query_schemas import AttemptConnectivityStatus
from app.domains.attempts.query_service import AttemptQueryService
from app.domains.attempts.repository import AttemptRepository
from app.domains.attempts.service import AttemptStateError
from app.domains.exams.models import ExamStatus


def context(*, is_makeup: bool = False):
    authorization_id = uuid4() if is_makeup else None
    return SimpleNamespace(
        student_id=uuid4(),
        candidate_id=uuid4(),
        exam_id=uuid4(),
        makeup_authorization_id=authorization_id,
        is_makeup=is_makeup,
    )


class AttemptHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_attempt_heartbeat_updates_liveness_only(self) -> None:
        db = AsyncMock()
        now = datetime.now(UTC) - timedelta(minutes=1)
        attempt = SimpleNamespace(
            id=uuid4(),
            status=AttemptStatus.IN_PROGRESS,
            last_heartbeat_at=now,
        )
        exam = SimpleNamespace(id=uuid4(), status=ExamStatus.ACTIVE)
        candidate = SimpleNamespace(id=uuid4())
        current_context = context()

        with (
            patch.object(
                AttemptService,
                "_get_current_attempt",
                new=AsyncMock(return_value=(attempt, candidate, exam)),
            ),
            patch.object(
                AttemptRepository,
                "save_attempt",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ) as save_attempt,
            patch.object(
                AttemptService,
                "remaining_seconds",
                new=AsyncMock(return_value=1234),
            ),
        ):
            response = await AttemptService.heartbeat_current(
                db,
                context=current_context,
            )

        self.assertEqual(response.attempt_id, attempt.id)
        self.assertEqual(response.remaining_seconds, 1234)
        self.assertFalse(response.exam_suspended)
        self.assertGreater(attempt.last_heartbeat_at, now)
        save_attempt.assert_awaited_once_with(db, attempt)
        db.commit.assert_awaited_once()

    async def test_suspended_exam_still_accepts_heartbeat(self) -> None:
        db = AsyncMock()
        attempt = SimpleNamespace(
            id=uuid4(),
            status=AttemptStatus.IN_PROGRESS,
            last_heartbeat_at=datetime.now(UTC),
        )
        exam = SimpleNamespace(id=uuid4(), status=ExamStatus.SUSPENDED)
        with (
            patch.object(
                AttemptService,
                "_get_current_attempt",
                new=AsyncMock(return_value=(attempt, SimpleNamespace(), exam)),
            ),
            patch.object(AttemptRepository, "save_attempt", new=AsyncMock()),
            patch.object(
                AttemptService,
                "remaining_seconds",
                new=AsyncMock(return_value=900),
            ),
        ):
            response = await AttemptService.heartbeat_current(db, context=context())

        self.assertTrue(response.exam_suspended)
        db.commit.assert_awaited_once()

    async def test_finalizing_exam_rejects_candidate_heartbeat(self) -> None:
        for status in (ExamStatus.CLOSING, ExamStatus.CANCELLING, ExamStatus.CANCELLED):
            with self.subTest(status=status):
                db = AsyncMock()
                attempt = SimpleNamespace(
                    id=uuid4(),
                    status=AttemptStatus.IN_PROGRESS,
                    last_heartbeat_at=datetime.now(UTC),
                )
                exam = SimpleNamespace(id=uuid4(), status=status)
                with (
                    patch.object(
                        AttemptService,
                        "_get_current_attempt",
                        new=AsyncMock(return_value=(attempt, SimpleNamespace(), exam)),
                    ),
                    self.assertRaises(AttemptStateError),
                ):
                    await AttemptService.heartbeat_current(db, context=context())
                db.commit.assert_not_awaited()

    async def test_makeup_attempt_can_heartbeat_on_closed_original_exam(self) -> None:
        db = AsyncMock()
        attempt = SimpleNamespace(
            id=uuid4(),
            status=AttemptStatus.IN_PROGRESS,
            last_heartbeat_at=datetime.now(UTC),
        )
        exam = SimpleNamespace(id=uuid4(), status=ExamStatus.CLOSED)
        with (
            patch.object(
                AttemptService,
                "_get_current_attempt",
                new=AsyncMock(return_value=(attempt, SimpleNamespace(), exam)),
            ),
            patch.object(AttemptRepository, "save_attempt", new=AsyncMock()),
            patch.object(
                AttemptService,
                "remaining_seconds",
                new=AsyncMock(return_value=400),
            ),
        ):
            response = await AttemptService.heartbeat_current(
                db,
                context=context(is_makeup=True),
            )

        self.assertEqual(response.remaining_seconds, 400)
        self.assertFalse(response.exam_suspended)
        db.commit.assert_awaited_once()


class AttemptConnectivityTests(unittest.TestCase):
    def test_connectivity_thresholds(self) -> None:
        now = datetime.now(UTC)

        def attempt(*, age: int, status: AttemptStatus = AttemptStatus.IN_PROGRESS):
            return SimpleNamespace(
                status=status,
                last_heartbeat_at=now - timedelta(seconds=age),
            )

        self.assertEqual(
            AttemptQueryService._connectivity(attempt=attempt(age=20), at=now)[0],
            AttemptConnectivityStatus.ONLINE,
        )
        self.assertEqual(
            AttemptQueryService._connectivity(attempt=attempt(age=70), at=now)[0],
            AttemptConnectivityStatus.RECENTLY_DISCONNECTED,
        )
        self.assertEqual(
            AttemptQueryService._connectivity(attempt=attempt(age=180), at=now)[0],
            AttemptConnectivityStatus.STALE,
        )
        self.assertEqual(
            AttemptQueryService._connectivity(
                attempt=attempt(age=180, status=AttemptStatus.SUBMITTED),
                at=now,
            )[0],
            AttemptConnectivityStatus.TERMINAL,
        )


if __name__ == "__main__":
    unittest.main()
