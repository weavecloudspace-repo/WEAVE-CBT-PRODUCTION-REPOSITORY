from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.domains.candidates.exceptions import CandidateRosterError
from app.domains.candidates.lifecycle_service import CandidateService
from app.domains.candidates.router import retry_failed_roster
from app.domains.exams.models import ExamRosterStatus, ExamStatus


class ManualRosterRetryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.exam_id = uuid4()
        self.actor = SimpleNamespace(is_active=True, role="admin")
        self.db = SimpleNamespace(commit=AsyncMock())

    async def test_initial_failed_roster_returns_to_pending(self) -> None:
        exam = SimpleNamespace(
            id=self.exam_id,
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.FAILED,
            roster_version=0,
            roster_error="Initial roster preparation failed",
        )

        with (
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ) as get_exam,
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.get_latest_child_revision",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.save_exam",
                AsyncMock(),
            ) as save_exam,
        ):
            returned_exam, recovery_mode = await CandidateService.retry_failed_roster(
                self.db,
                actor=self.actor,
                exam_id=self.exam_id,
            )

        self.assertIs(returned_exam, exam)
        self.assertEqual(recovery_mode, "prepare")
        self.assertEqual(exam.roster_status, ExamRosterStatus.PENDING)
        self.assertIsNone(exam.roster_error)
        get_exam.assert_awaited_once_with(
            self.db,
            exam_id=self.exam_id,
            lock=True,
        )
        save_exam.assert_awaited_once_with(self.db, exam)
        self.db.commit.assert_awaited_once_with()

    async def test_failed_existing_roster_returns_to_stale(self) -> None:
        exam = SimpleNamespace(
            id=self.exam_id,
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.FAILED,
            roster_version=4,
            roster_error="Roster reconciliation failed",
        )

        with (
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.get_latest_child_revision",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.save_exam",
                AsyncMock(),
            ),
        ):
            _, recovery_mode = await CandidateService.retry_failed_roster(
                self.db,
                actor=self.actor,
                exam_id=self.exam_id,
            )

        self.assertEqual(recovery_mode, "reconcile")
        self.assertEqual(exam.roster_status, ExamRosterStatus.STALE)
        self.assertIsNone(exam.roster_error)
        self.db.commit.assert_awaited_once_with()

    async def test_retry_rejects_non_failed_roster(self) -> None:
        exam = SimpleNamespace(
            id=self.exam_id,
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.READY,
            roster_version=2,
            roster_error=None,
        )

        with (
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.get_latest_child_revision",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.save_exam",
                AsyncMock(),
            ) as save_exam,
            self.assertRaisesRegex(CandidateRosterError, "FAILED state"),
        ):
            await CandidateService.retry_failed_roster(
                self.db,
                actor=self.actor,
                exam_id=self.exam_id,
            )

        save_exam.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_retry_rejects_superseded_failed_roster(self) -> None:
        exam = SimpleNamespace(
            id=self.exam_id,
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.FAILED,
            roster_version=3,
            roster_error="Old failure",
        )
        child = SimpleNamespace(id=uuid4())

        with (
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.get_latest_child_revision",
                AsyncMock(return_value=child),
            ) as get_child,
            patch(
                "app.domains.candidates.lifecycle_service.ExamRepository.save_exam",
                AsyncMock(),
            ) as save_exam,
            self.assertRaisesRegex(CandidateRosterError, "superseded"),
        ):
            await CandidateService.retry_failed_roster(
                self.db,
                actor=self.actor,
                exam_id=self.exam_id,
            )

        get_child.assert_awaited_once_with(self.db, self.exam_id)
        save_exam.assert_not_awaited()
        self.db.commit.assert_not_awaited()
        self.assertEqual(exam.roster_status, ExamRosterStatus.FAILED)
        self.assertEqual(exam.roster_error, "Old failure")


class ManualRosterRetryEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_enqueues_reconciliation_after_durable_transition(
        self,
    ) -> None:
        exam_id = uuid4()
        exam = SimpleNamespace(
            id=exam_id,
            roster_status=ExamRosterStatus.STALE,
            roster_version=3,
        )
        actor = SimpleNamespace(is_active=True, role="admin")
        db = SimpleNamespace()

        with (
            patch(
                "app.domains.candidates.router.CandidateService.retry_failed_roster",
                AsyncMock(return_value=(exam, "reconcile")),
            ),
            patch(
                "app.domains.candidates.router.arq_producer.enqueue",
                AsyncMock(return_value=False),
            ) as enqueue,
        ):
            response = await retry_failed_roster(exam_id, db, actor)

        enqueue.assert_awaited_once_with("reconcile_exam_roster", str(exam_id))
        self.assertEqual(response.recovery_mode, "reconcile")
        self.assertFalse(response.queued)
        self.assertEqual(response.roster_status, ExamRosterStatus.STALE.value)


if __name__ == "__main__":
    unittest.main()
