from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch
from uuid import uuid4

from app.domains.exams.models import ExamRosterStatus, ExamStatus
from app.workers.candidates import prepare_exam_roster, reconcile_exam_roster
from app.workers.maintenance import recover_background_work


class _AsyncSessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class RosterReconciliationWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_sealed_roster_is_reconciled_in_place(self) -> None:
        exam_id = uuid4()
        session = SimpleNamespace()
        exam = SimpleNamespace(
            id=exam_id,
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.STALE,
        )

        with (
            patch(
                "app.workers.candidates.async_session_factory",
                Mock(return_value=_AsyncSessionContext(session)),
            ),
            patch(
                "app.workers.candidates.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ) as get_exam,
            patch(
                "app.workers.candidates.ExamRepository.get_latest_child_revision",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.workers.candidates.CandidateService.reconcile_roster",
                AsyncMock(),
            ) as reconcile,
        ):
            await reconcile_exam_roster({}, str(exam_id))

        get_exam.assert_awaited_once_with(
            session,
            exam_id=exam_id,
            lock=True,
        )
        reconcile.assert_awaited_once_with(
            session,
            exam_id=exam_id,
        )

    async def test_duplicate_reconciliation_delivery_is_noop_after_ready(self) -> None:
        exam_id = uuid4()
        session = SimpleNamespace()
        exam = SimpleNamespace(
            id=exam_id,
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.READY,
        )

        with (
            patch(
                "app.workers.candidates.async_session_factory",
                Mock(return_value=_AsyncSessionContext(session)),
            ),
            patch(
                "app.workers.candidates.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch(
                "app.workers.candidates.ExamRepository.get_latest_child_revision",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.workers.candidates.CandidateService.reconcile_roster",
                AsyncMock(),
            ) as reconcile,
        ):
            await reconcile_exam_roster({}, str(exam_id))

        reconcile.assert_not_awaited()

    async def test_queued_reconciliation_for_superseded_revision_is_ignored(
        self,
    ) -> None:
        exam_id = uuid4()
        session = SimpleNamespace()
        exam = SimpleNamespace(
            id=exam_id,
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.STALE,
        )
        child = SimpleNamespace(id=uuid4())

        with (
            patch(
                "app.workers.candidates.async_session_factory",
                Mock(return_value=_AsyncSessionContext(session)),
            ),
            patch(
                "app.workers.candidates.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch(
                "app.workers.candidates.ExamRepository.get_latest_child_revision",
                AsyncMock(return_value=child),
            ) as get_child,
            patch(
                "app.workers.candidates.CandidateService.reconcile_roster",
                AsyncMock(),
            ) as reconcile,
        ):
            await reconcile_exam_roster({}, str(exam_id))

        get_child.assert_awaited_once_with(session, exam_id)
        reconcile.assert_not_awaited()
        self.assertEqual(exam.roster_status, ExamRosterStatus.STALE)

    async def test_queued_preparation_for_superseded_revision_is_ignored(self) -> None:
        exam_id = uuid4()
        session = SimpleNamespace()
        exam = SimpleNamespace(
            id=exam_id,
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.PENDING,
        )
        child = SimpleNamespace(id=uuid4())

        with (
            patch(
                "app.workers.candidates.async_session_factory",
                Mock(return_value=_AsyncSessionContext(session)),
            ),
            patch(
                "app.workers.candidates.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch(
                "app.workers.candidates.ExamRepository.get_latest_child_revision",
                AsyncMock(return_value=child),
            ),
            patch(
                "app.workers.candidates.CandidateService.prepare_roster",
                AsyncMock(),
            ) as prepare,
        ):
            await prepare_exam_roster({}, str(exam_id))

        prepare.assert_not_awaited()
        self.assertEqual(exam.roster_status, ExamRosterStatus.PENDING)


class RosterMaintenanceRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_maintenance_recovers_pending_and_stale_rosters_separately(
        self,
    ) -> None:
        pending_exam_id = uuid4()
        stale_exam_id = uuid4()
        redis = SimpleNamespace(enqueue_job=AsyncMock())

        with (
            patch(
                "app.workers.maintenance._recover_stale_result_batches",
                AsyncMock(return_value=set()),
            ),
            patch(
                "app.workers.maintenance._list_roster_exam_ids_needing_recovery",
                AsyncMock(return_value=([pending_exam_id], [stale_exam_id])),
            ),
            patch(
                "app.workers.maintenance._list_exam_execution_recovery_ids",
                AsyncMock(return_value=([], [], [])),
            ),
            patch(
                "app.workers.maintenance._list_result_exam_ids_needing_recovery",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.workers.maintenance._filter_approved_exam_ids",
                AsyncMock(return_value=set()),
            ),
        ):
            result = await recover_background_work({"redis": redis})

        self.assertEqual(
            redis.enqueue_job.await_args_list,
            [
                call("finalize_expired_attempts", _job_id="exam-timeout-sweep"),
                call("prepare_exam_roster", str(pending_exam_id)),
                call("reconcile_exam_roster", str(stale_exam_id)),
            ],
        )
        self.assertEqual(result["roster_jobs_enqueued"], 1)
        self.assertEqual(result["roster_reconcile_jobs_enqueued"], 1)


if __name__ == "__main__":
    unittest.main()
