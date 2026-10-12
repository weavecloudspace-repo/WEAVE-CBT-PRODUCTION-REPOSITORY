from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch
from uuid import uuid4

from sqlalchemy import inspect
from sqlalchemy.orm import Session, make_transient_to_detached

from app.domains.attempts.models import AttemptStatus, ExamAttempt
from app.workers.exams import finalize_expired_attempts


class _AsyncSessionContext:
    def __init__(self, session, *, on_close=None):
        self.session = session
        self.on_close = on_close

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        if self.on_close is not None:
            self.on_close()
        return False


class ExpiredAttemptWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_reads_timing_before_rollback_expires_orm_rows(self):
        now = datetime.now(UTC)
        attempts = [
            ExamAttempt(
                id=uuid4(),
                active_since=active_since,
                time_limit_seconds=60,
                elapsed_seconds=elapsed_seconds,
                status=AttemptStatus.IN_PROGRESS,
            )
            for active_since, elapsed_seconds in [
                (now - timedelta(minutes=2), 0),
                (now + timedelta(minutes=2), 0),
                (None, 0),
                (now - timedelta(seconds=1), 90),
            ]
        ]
        expired_ids = [attempts[0].id, attempts[3].id]
        # Attach loaded rows without issuing SQL. Real SQLAlchemy rollback then
        # expires their fields, reproducing the worker's original failure.
        orm_session = Session()
        self.addCleanup(orm_session.close)
        for attempt in attempts:
            make_transient_to_detached(attempt)
            orm_session.add(attempt)

        scan_session = SimpleNamespace(
            rollback=AsyncMock(side_effect=orm_session.rollback),
        )
        finalize_session = SimpleNamespace(rollback=AsyncMock())
        exam_id = uuid4()

        with (
            patch(
                "app.workers.exams.async_session_factory",
                Mock(
                    side_effect=[
                        _AsyncSessionContext(scan_session, on_close=orm_session.close),
                        _AsyncSessionContext(finalize_session),
                        _AsyncSessionContext(finalize_session),
                    ]
                ),
            ),
            patch(
                "app.workers.exams.AttemptRepository.list_attempts",
                AsyncMock(return_value=attempts),
            ),
            patch(
                "app.workers.exams.AttemptService.finalize_if_expired",
                AsyncMock(return_value=exam_id),
            ) as finalize,
            patch(
                "app.workers.exams.AttemptRepository.get_attempt_by_id",
                AsyncMock(return_value=SimpleNamespace(status=AttemptStatus.SUBMITTED)),
            ),
            patch(
                "app.workers.exams.evaluate_exam_completion",
                AsyncMock(),
            ) as evaluate,
        ):
            result = await finalize_expired_attempts({})

        self.assertTrue(inspect(attempts[0]).detached)
        self.assertIn("active_since", inspect(attempts[0]).expired_attributes)
        self.assertEqual(
            [entry.kwargs["attempt_id"] for entry in finalize.await_args_list],
            expired_ids,
        )
        self.assertEqual(evaluate.await_args_list, [call({}, str(exam_id))])
        self.assertEqual(
            result,
            {
                "expired_attempts_scanned": 2,
                "expired_attempts_finalized": 2,
                "completion_exams_rechecked": 1,
            },
        )
