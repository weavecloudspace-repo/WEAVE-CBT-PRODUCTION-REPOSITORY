from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DEBUG"] = "false"

from app.core.exceptions import AcademicAuthorizationError
from app.domains.attempts.repository import AttemptRepository
from app.domains.candidates.models import CandidateStatus
from app.domains.candidates.repository import CandidateRepository
from app.domains.candidates.service import CandidateService
from app.domains.exams.models import ExamRosterStatus, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.exams.timetable_service import ExamTimetableService


def actor(*, role: str = "admin", membership_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        role=role,
        is_active=True,
        weave_membership_id=(
            str(membership_id or uuid4()) if role == "teacher" else None
        ),
    )


def exam(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "title": "Mathematics CA 1",
        "curriculum_subject_id": uuid4(),
        "session_id": uuid4(),
        "term_id": uuid4(),
        "status": ExamStatus.SEALED,
        "roster_status": ExamRosterStatus.READY,
        "roster_version": 2,
        "roster_candidate_count": 3,
        "scheduled_start_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def candidate(**overrides) -> SimpleNamespace:
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "exam_id": uuid4(),
        "enrollment_id": uuid4(),
        "student_id": uuid4(),
        "class_id": uuid4(),
        "admission_number": "ADM-001",
        "display_name": "Ada Lovelace",
        "status": CandidateStatus.ELIGIBLE,
        "status_reason": None,
        "roster_version": 2,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def authorization(**overrides) -> SimpleNamespace:
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "candidate_id": uuid4(),
        "granted_by_actor_id": uuid4(),
        "reason": "Late transport",
        "granted_at": now,
        "expires_at": None,
        "consumed_at": None,
        "revoked_at": None,
        "revoked_by_actor_id": None,
        "revocation_reason": None,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def makeup_authorization(**overrides) -> SimpleNamespace:
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "candidate_id": uuid4(),
        "approved_by_actor_id": uuid4(),
        "reason": "Missed original sitting",
        "approved_at": now,
        "consumed_at": None,
        "revoked_at": None,
        "revoked_by_actor_id": None,
        "revocation_reason": None,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class CandidateServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_can_list_roster(self) -> None:
        db = AsyncMock()
        current_exam = exam()
        row = candidate(exam_id=current_exam.id)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                CandidateRepository,
                "list_candidates_for_exam",
                new=AsyncMock(return_value=[row]),
            ) as list_candidates,
            patch.object(
                CandidateRepository,
                "count_candidates_for_exam",
                new=AsyncMock(return_value=1),
            ),
        ):
            result = await CandidateService.list_roster(
                db,
                actor=actor(),
                exam_id=current_exam.id,
                status=CandidateStatus.ELIGIBLE,
                offset=5,
                limit=10,
            )

        self.assertEqual(result.total, 1)
        self.assertEqual(result.candidates[0].id, row.id)
        list_candidates.assert_awaited_once_with(
            db,
            current_exam.id,
            status=CandidateStatus.ELIGIBLE,
            class_id=None,
            offset=5,
            limit=10,
        )

    async def test_assigned_invigilator_can_list_roster(self) -> None:
        db = AsyncMock()
        teacher_id = uuid4()
        current_actor = actor(role="teacher", membership_id=teacher_id)
        current_exam = exam()

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_invigilator",
                new=AsyncMock(return_value=SimpleNamespace()),
            ) as get_invigilator,
            patch.object(
                CandidateRepository,
                "list_candidates_for_exam",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                CandidateRepository,
                "count_candidates_for_exam",
                new=AsyncMock(return_value=0),
            ),
        ):
            await CandidateService.list_roster(
                db,
                actor=current_actor,
                exam_id=current_exam.id,
            )

        get_invigilator.assert_awaited_once_with(db, current_exam.id, teacher_id)

    async def test_unrelated_teacher_cannot_list_roster(self) -> None:
        db = AsyncMock()
        current_exam = exam()

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_invigilator",
                new=AsyncMock(return_value=None),
            ),
            self.assertRaises(AcademicAuthorizationError),
        ):
            await CandidateService.list_roster(
                db,
                actor=actor(role="teacher"),
                exam_id=current_exam.id,
            )

    async def test_class_filter_must_belong_to_exam_target_classes(self) -> None:
        db = AsyncMock()
        current_exam = exam()

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_target_class",
                new=AsyncMock(return_value=None),
            ),
            self.assertRaisesRegex(ValueError, "Class is not part"),
        ):
            await CandidateService.list_roster(
                db,
                actor=actor(),
                exam_id=current_exam.id,
                class_id=uuid4(),
            )

    async def test_non_ready_roster_can_be_listed(self) -> None:
        db = AsyncMock()
        current_exam = exam(roster_status=ExamRosterStatus.FAILED)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                CandidateRepository,
                "list_candidates_for_exam",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                CandidateRepository,
                "count_candidates_for_exam",
                new=AsyncMock(return_value=0),
            ),
        ):
            result = await CandidateService.list_roster(
                db,
                actor=actor(),
                exam_id=current_exam.id,
            )

        self.assertEqual(result.roster_status, ExamRosterStatus.FAILED.value)

    async def test_block_and_unblock_happy_paths(self) -> None:
        admin = actor()

        blocked = candidate()
        current_exam = exam(id=blocked.exam_id)
        db = AsyncMock()
        with (
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=blocked),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                CandidateRepository,
                "save_candidate",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            result = await CandidateService.block_candidate(
                db,
                actor=admin,
                candidate_id=blocked.id,
                reason="  Misconduct concern  ",
            )

        self.assertEqual(result.status, CandidateStatus.BLOCKED.value)
        self.assertEqual(blocked.status_reason, "Misconduct concern")
        db.commit.assert_awaited_once()

        db = AsyncMock()
        with (
            patch.object(
                ExamTimetableService, "level_id", new=AsyncMock(return_value=uuid4())
            ),
            patch.object(ExamTimetableService, "acquire_level_lock", new=AsyncMock()),
            patch.object(
                ExamTimetableService,
                "acquire_operational_candidate_lock",
                new=AsyncMock(),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=blocked),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                CandidateRepository,
                "save_candidate",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            result = await CandidateService.unblock_candidate(
                db,
                actor=admin,
                candidate_id=blocked.id,
            )

        self.assertEqual(result.status, CandidateStatus.ELIGIBLE.value)
        self.assertIsNone(blocked.status_reason)
        db.commit.assert_awaited_once()

    async def test_invalid_block_unblock_transitions_are_rejected(self) -> None:
        for status in (CandidateStatus.BLOCKED, CandidateStatus.WITHDRAWN):
            with self.subTest(block_status=status):
                db = AsyncMock()
                row = candidate(status=status)
                with (
                    patch.object(
                        CandidateRepository,
                        "get_candidate_by_id",
                        new=AsyncMock(return_value=row),
                    ),
                    patch.object(
                        ExamRepository,
                        "get_exam_by_id",
                        new=AsyncMock(return_value=exam(id=row.exam_id)),
                    ),
                    self.assertRaisesRegex(ValueError, "eligible"),
                ):
                    await CandidateService.block_candidate(
                        db,
                        actor=actor(),
                        candidate_id=row.id,
                        reason="Stop",
                    )
                db.commit.assert_not_awaited()

        db = AsyncMock()
        row = candidate(status=CandidateStatus.WITHDRAWN)
        with (
            patch.object(
                ExamTimetableService, "level_id", new=AsyncMock(return_value=uuid4())
            ),
            patch.object(ExamTimetableService, "acquire_level_lock", new=AsyncMock()),
            patch.object(
                ExamTimetableService,
                "acquire_operational_candidate_lock",
                new=AsyncMock(),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=exam(id=row.exam_id)),
            ),
            self.assertRaisesRegex(ValueError, "blocked"),
        ):
            await CandidateService.unblock_candidate(
                db,
                actor=actor(),
                candidate_id=row.id,
            )
        db.commit.assert_not_awaited()

    async def test_cancelled_or_closed_exam_rejects_candidate_mutations(self) -> None:
        admin = actor()
        for lifecycle_status in (ExamStatus.CANCELLED, ExamStatus.CLOSED):
            with self.subTest(status=lifecycle_status):
                db = AsyncMock()
                row = candidate()
                with (
                    patch.object(
                        CandidateRepository,
                        "get_candidate_by_id",
                        new=AsyncMock(return_value=row),
                    ),
                    patch.object(
                        ExamRepository,
                        "get_exam_by_id",
                        new=AsyncMock(
                            return_value=exam(id=row.exam_id, status=lifecycle_status)
                        ),
                    ),
                    self.assertRaisesRegex(ValueError, "read-only"),
                ):
                    await CandidateService.block_candidate(
                        db,
                        actor=admin,
                        candidate_id=row.id,
                        reason="Stop",
                    )
                db.commit.assert_not_awaited()

    async def test_late_start_grant_validation_and_success(self) -> None:
        db = AsyncMock()
        admin = actor()
        row = candidate()
        current_exam = exam(id=row.exam_id, status=ExamStatus.ACTIVE)
        expires_at = datetime.now(UTC) + timedelta(minutes=10)

        async def add_authorization(_db, item):
            now = datetime.now(UTC)
            item.id = uuid4()
            item.created_at = now
            item.updated_at = now
            return item

        with (
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                CandidateRepository,
                "add_late_start_authorization",
                new=AsyncMock(side_effect=add_authorization),
            ) as add_authorization,
        ):
            result = await CandidateService.grant_late_start(
                db,
                actor=admin,
                candidate_id=row.id,
                reason="  Transport delay  ",
                expires_at=expires_at,
            )

        self.assertEqual(result.reason, "Transport delay")
        self.assertEqual(result.granted_by_actor_id, admin.id)
        add_authorization.assert_awaited_once()
        db.commit.assert_awaited_once()

        db = AsyncMock()
        with self.assertRaisesRegex(ValueError, "reason"):
            await CandidateService.grant_late_start(
                db,
                actor=admin,
                candidate_id=row.id,
                reason=" ",
            )
        db.commit.assert_not_awaited()

    async def test_expired_late_start_grant_is_rejected(self) -> None:
        db = AsyncMock()
        with self.assertRaisesRegex(ValueError, "past"):
            await CandidateService.grant_late_start(
                db,
                actor=actor(),
                candidate_id=uuid4(),
                reason="Late",
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        db.commit.assert_not_awaited()

    async def test_blocked_or_withdrawn_candidate_cannot_receive_late_start(
        self,
    ) -> None:
        for status in (CandidateStatus.BLOCKED, CandidateStatus.WITHDRAWN):
            with self.subTest(status=status):
                db = AsyncMock()
                row = candidate(status=status)
                with (
                    patch.object(
                        CandidateRepository,
                        "get_candidate_by_id",
                        new=AsyncMock(return_value=row),
                    ),
                    patch.object(
                        ExamRepository,
                        "get_exam_by_id",
                        new=AsyncMock(
                            return_value=exam(id=row.exam_id, status=ExamStatus.ACTIVE)
                        ),
                    ),
                    self.assertRaisesRegex(ValueError, "eligible"),
                ):
                    await CandidateService.grant_late_start(
                        db,
                        actor=actor(),
                        candidate_id=row.id,
                        reason="Late",
                    )
                db.commit.assert_not_awaited()

    async def test_revoke_late_start_success(self) -> None:
        db = AsyncMock()
        admin = actor()
        row = candidate()
        auth = authorization(candidate_id=row.id)

        with (
            patch.object(
                CandidateRepository,
                "get_late_start_authorization_by_id",
                new=AsyncMock(return_value=auth),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(
                    return_value=exam(id=row.exam_id, status=ExamStatus.ACTIVE)
                ),
            ),
            patch.object(
                CandidateRepository,
                "save_late_start_authorization",
                new=AsyncMock(side_effect=lambda _db, item: item),
            ),
        ):
            result = await CandidateService.revoke_late_start(
                db,
                actor=admin,
                authorization_id=auth.id,
                reason="  Wrong candidate  ",
            )

        self.assertIsNotNone(result.revoked_at)
        self.assertEqual(result.revoked_by_actor_id, admin.id)
        self.assertEqual(result.revocation_reason, "Wrong candidate")
        db.commit.assert_awaited_once()

    async def test_double_revoke_is_rejected(self) -> None:
        db = AsyncMock()
        row = candidate()
        auth = authorization(candidate_id=row.id, revoked_at=datetime.now(UTC))

        with (
            patch.object(
                CandidateRepository,
                "get_late_start_authorization_by_id",
                new=AsyncMock(return_value=auth),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(
                    return_value=exam(id=row.exam_id, status=ExamStatus.ACTIVE)
                ),
            ),
            self.assertRaisesRegex(ValueError, "already"),
        ):
            await CandidateService.revoke_late_start(
                db,
                actor=actor(),
                authorization_id=auth.id,
                reason="No longer needed",
            )
        db.commit.assert_not_awaited()

    async def test_consumed_authorization_revoke_is_rejected(self) -> None:
        db = AsyncMock()
        row = candidate()
        auth = authorization(candidate_id=row.id, consumed_at=datetime.now(UTC))

        with (
            patch.object(
                CandidateRepository,
                "get_late_start_authorization_by_id",
                new=AsyncMock(return_value=auth),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(
                    return_value=exam(id=row.exam_id, status=ExamStatus.ACTIVE)
                ),
            ),
            self.assertRaisesRegex(ValueError, "Consumed"),
        ):
            await CandidateService.revoke_late_start(
                db,
                actor=actor(),
                authorization_id=auth.id,
                reason="No longer needed",
            )
        db.commit.assert_not_awaited()

    async def test_authorization_history_listing(self) -> None:
        db = AsyncMock()
        teacher_id = uuid4()
        current_actor = actor(role="teacher", membership_id=teacher_id)
        row = candidate()
        current_exam = exam(id=row.exam_id)
        first = authorization(candidate_id=row.id)
        second = authorization(candidate_id=row.id)

        with (
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_invigilator",
                new=AsyncMock(return_value=SimpleNamespace()),
            ),
            patch.object(
                CandidateRepository,
                "list_late_start_authorizations",
                new=AsyncMock(return_value=[first, second]),
            ) as list_authorizations,
        ):
            result = await CandidateService.list_late_start_authorizations(
                db,
                actor=current_actor,
                candidate_id=row.id,
            )

        self.assertEqual([item.id for item in result], [first.id, second.id])
        list_authorizations.assert_awaited_once_with(db, row.id)

    async def test_integrity_error_rolls_back_without_exposing_constraint(self) -> None:
        db = AsyncMock()
        row = candidate()
        integrity_error = IntegrityError("update", {}, Exception("constraint-name"))

        with (
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=exam(id=row.exam_id)),
            ),
            patch.object(
                CandidateRepository,
                "save_candidate",
                new=AsyncMock(side_effect=integrity_error),
            ),
            self.assertRaisesRegex(ValueError, "could not be blocked") as ctx,
        ):
            await CandidateService.block_candidate(
                db,
                actor=actor(),
                candidate_id=row.id,
                reason="Stop",
            )

        self.assertNotIn("constraint-name", str(ctx.exception))
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    async def test_list_missed_candidates_includes_makeup_authorization(self) -> None:
        db = AsyncMock()
        current_exam = exam(status=ExamStatus.CLOSED)
        row = candidate(exam_id=current_exam.id)
        auth = makeup_authorization(candidate_id=row.id)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                CandidateRepository,
                "list_missed_candidates_for_exam",
                new=AsyncMock(return_value=[row]),
            ) as list_missed,
            patch.object(
                CandidateRepository,
                "count_missed_candidates_for_exam",
                new=AsyncMock(return_value=1),
            ) as count_missed,
            patch.object(
                CandidateRepository,
                "list_active_makeup_authorizations_for_candidates",
                new=AsyncMock(return_value=[auth]),
            ) as list_authorizations,
        ):
            result = await CandidateService.list_missed_candidates(
                db,
                actor=actor(),
                exam_id=current_exam.id,
                offset=5,
                limit=10,
            )

        self.assertEqual(result.exam_id, current_exam.id)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.candidates[0].candidate.id, row.id)
        self.assertEqual(result.candidates[0].makeup_authorization.id, auth.id)
        list_missed.assert_awaited_once_with(
            db,
            current_exam.id,
            offset=5,
            limit=10,
        )
        count_missed.assert_awaited_once_with(db, current_exam.id)
        list_authorizations.assert_awaited_once_with(db, [row.id])

    async def test_list_missed_candidates_requires_closed_exam(self) -> None:
        db = AsyncMock()
        current_exam = exam(status=ExamStatus.ACTIVE)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            self.assertRaisesRegex(ValueError, "closed"),
        ):
            await CandidateService.list_missed_candidates(
                db,
                actor=actor(),
                exam_id=current_exam.id,
            )

    async def test_approve_makeup_success(self) -> None:
        db = AsyncMock()
        admin = actor()
        row = candidate()
        current_exam = exam(id=row.exam_id, status=ExamStatus.CLOSED)

        async def add_authorization(_db, item):
            now = datetime.now(UTC)
            item.id = uuid4()
            item.consumed_at = None
            item.revoked_at = None
            item.revoked_by_actor_id = None
            item.revocation_reason = None
            item.created_at = now
            item.updated_at = now
            return item

        with (
            patch("app.domains.candidates.service.require_current_makeup_term", AsyncMock()),
            patch("app.domains.candidates.service.ExamExecutionRepository.get_control", AsyncMock(return_value=None)),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                AttemptRepository,
                "get_attempt_by_candidate_id",
                new=AsyncMock(return_value=None),
            ) as get_attempt,
            patch.object(
                CandidateRepository,
                "get_active_makeup_authorization",
                new=AsyncMock(return_value=None),
            ) as get_existing,
            patch.object(
                CandidateRepository,
                "add_makeup_authorization",
                new=AsyncMock(side_effect=add_authorization),
            ) as add_makeup,
        ):
            result = await CandidateService.approve_makeup(
                db,
                actor=admin,
                candidate_id=row.id,
                reason="  Medical emergency  ",
            )

        self.assertEqual(result.reason, "Medical emergency")
        self.assertEqual(result.candidate_id, row.id)
        self.assertEqual(result.approved_by_actor_id, admin.id)
        get_attempt.assert_awaited_once_with(db, candidate_id=row.id, lock=True)
        get_existing.assert_awaited_once_with(db, row.id, lock=True)
        add_makeup.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_approve_makeup_rejects_candidate_with_attempt(self) -> None:
        db = AsyncMock()
        row = candidate()

        with (
            patch("app.domains.candidates.service.require_current_makeup_term", AsyncMock()),
            patch("app.domains.candidates.service.ExamExecutionRepository.get_control", AsyncMock(return_value=None)),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(
                    return_value=exam(id=row.exam_id, status=ExamStatus.CLOSED)
                ),
            ),
            patch.object(
                AttemptRepository,
                "get_attempt_by_candidate_id",
                new=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
            ),
            self.assertRaisesRegex(ValueError, "attempt was already recorded"),
        ):
            await CandidateService.approve_makeup(
                db,
                actor=actor(),
                candidate_id=row.id,
                reason="Missed",
            )

        db.commit.assert_not_awaited()

    async def test_approve_makeup_rejects_existing_active_authorization(self) -> None:
        db = AsyncMock()
        row = candidate()

        with (
            patch("app.domains.candidates.service.require_current_makeup_term", AsyncMock()),
            patch("app.domains.candidates.service.ExamExecutionRepository.get_control", AsyncMock(return_value=None)),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(
                    return_value=exam(id=row.exam_id, status=ExamStatus.CLOSED)
                ),
            ),
            patch.object(
                AttemptRepository,
                "get_attempt_by_candidate_id",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                CandidateRepository,
                "get_active_makeup_authorization",
                new=AsyncMock(return_value=makeup_authorization(candidate_id=row.id)),
            ),
            self.assertRaisesRegex(ValueError, "already has an active"),
        ):
            await CandidateService.approve_makeup(
                db,
                actor=actor(),
                candidate_id=row.id,
                reason="Missed",
            )

        db.commit.assert_not_awaited()

    async def test_revoke_makeup_success(self) -> None:
        db = AsyncMock()
        admin = actor()
        row = candidate()
        auth = makeup_authorization(candidate_id=row.id)

        with (
            patch.object(
                CandidateRepository,
                "get_makeup_authorization_by_id",
                new=AsyncMock(return_value=auth),
            ),
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(
                    return_value=exam(id=row.exam_id, status=ExamStatus.CLOSED)
                ),
            ),
            patch.object(
                CandidateRepository,
                "save_makeup_authorization",
                new=AsyncMock(side_effect=lambda _db, item: item),
            ) as save_makeup,
        ):
            result = await CandidateService.revoke_makeup(
                db,
                actor=admin,
                authorization_id=auth.id,
                reason="  Approved in error  ",
            )

        self.assertIsNotNone(result.revoked_at)
        self.assertEqual(result.revoked_by_actor_id, admin.id)
        self.assertEqual(result.revocation_reason, "Approved in error")
        save_makeup.assert_awaited_once_with(db, auth)
        db.commit.assert_awaited_once()

    async def test_revoke_makeup_rejects_consumed_authorization(self) -> None:
        db = AsyncMock()
        auth = makeup_authorization(consumed_at=datetime.now(UTC))

        with (
            patch.object(
                CandidateRepository,
                "get_makeup_authorization_by_id",
                new=AsyncMock(return_value=auth),
            ),
            self.assertRaisesRegex(ValueError, "Consumed"),
        ):
            await CandidateService.revoke_makeup(
                db,
                actor=actor(),
                authorization_id=auth.id,
                reason="No longer needed",
            )

        db.commit.assert_not_awaited()

    async def test_makeup_authorization_history_listing(self) -> None:
        db = AsyncMock()
        row = candidate()
        first = makeup_authorization(candidate_id=row.id)
        second = makeup_authorization(candidate_id=row.id)

        with (
            patch.object(
                CandidateRepository,
                "get_candidate_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=exam(id=row.exam_id)),
            ),
            patch.object(
                CandidateRepository,
                "list_makeup_authorizations",
                new=AsyncMock(return_value=[first, second]),
            ) as list_authorizations,
        ):
            result = await CandidateService.list_makeup_authorizations(
                db,
                actor=actor(),
                candidate_id=row.id,
            )

        self.assertEqual([item.id for item in result], [first.id, second.id])
        list_authorizations.assert_awaited_once_with(db, row.id)


if __name__ == "__main__":
    unittest.main()
