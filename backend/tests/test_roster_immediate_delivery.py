from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch
from uuid import uuid4

from app.workers.producer import roster_reconcile_job_id
from app.workers.roster_delivery import enqueue_stale_roster_reconciliations


class _AsyncSessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _TupleResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def tuples(self):
        return self

    def all(self):
        return self.rows


class ImmediateRosterDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_rosters_use_version_scoped_reconciliation_job_ids(
        self,
    ) -> None:
        first_exam_id = uuid4()
        second_exam_id = uuid4()
        session = SimpleNamespace(
            execute=AsyncMock(
                return_value=_TupleResult(
                    [
                        (first_exam_id, 6),
                        (second_exam_id, 2),
                    ]
                )
            ),
            rollback=AsyncMock(),
        )

        with (
            patch(
                "app.workers.roster_delivery.async_session_factory",
                Mock(return_value=_AsyncSessionContext(session)),
            ),
            patch(
                "app.workers.roster_delivery.arq_producer.enqueue",
                AsyncMock(side_effect=[True, True]),
            ) as enqueue,
        ):
            queued = await enqueue_stale_roster_reconciliations()

        self.assertEqual(queued, 2)
        session.execute.assert_awaited_once()
        session.rollback.assert_awaited_once_with()
        self.assertEqual(
            enqueue.await_args_list,
            [
                call(
                    "reconcile_exam_roster",
                    str(first_exam_id),
                    _job_id=roster_reconcile_job_id(first_exam_id, 6),
                ),
                call(
                    "reconcile_exam_roster",
                    str(second_exam_id),
                    _job_id=roster_reconcile_job_id(second_exam_id, 2),
                ),
            ],
        )

    async def test_new_roster_version_gets_a_new_immediate_job_identity(self) -> None:
        exam_id = uuid4()

        self.assertNotEqual(
            roster_reconcile_job_id(exam_id, 6),
            roster_reconcile_job_id(exam_id, 7),
        )


if __name__ == "__main__":
    unittest.main()
