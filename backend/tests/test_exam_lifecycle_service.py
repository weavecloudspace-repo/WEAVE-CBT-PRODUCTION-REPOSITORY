from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DEBUG"] = "false"

from app.core.exceptions import (
    AcademicAuthorizationError,
    AcademicScopeError,
)
from app.domains.academics.authorization import (
    AcademicAuthorizationService,
)
from app.domains.academics.eligibility import AcademicEligibilityService
from app.domains.academics.repository import AcademicRepository
from app.domains.exams.exceptions import (
    ExamAuthorizationError,
    ExamStateError,
)
from app.domains.exams.models import (
    ExamQuestionSelectionMode,
    ExamRosterStatus,
    ExamStatus,
)
from app.domains.exams.repository import ExamRepository
from app.domains.exams.schemas import (
    ExamInvigilatorAssignment,
    ExamResponse,
)
from app.domains.exams.service import ExamService
from app.domains.exams.timetable_service import ExamTimetableService
from app.domains.questions.models import QuestionType
from app.domains.questions.repository import QuestionRepository
from app.domains.runtime.repository import RuntimeRepository
from app.domains.sync.repository import SyncRepository

LEAD_ACTOR_ID = uuid4()


def actor(*, role: str = "teacher", actor_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=actor_id or (LEAD_ACTOR_ID if role == "teacher" else uuid4()),
        role=role,
        is_active=True,
        weave_membership_id=str(uuid4()) if role == "teacher" else None,
    )


def exam(**overrides) -> SimpleNamespace:
    future_start = datetime.now(UTC) + timedelta(days=1)
    values = {
        "id": uuid4(),
        "session_id": uuid4(),
        "term_id": uuid4(),
        "curriculum_subject_id": uuid4(),
        "assessment_scheme_id": uuid4(),
        "assessment_component_id": uuid4(),
        "question_bank_id": uuid4(),
        "question_selection_mode": ExamQuestionSelectionMode.RANDOM,
        "question_count": 1,
        "title": "Midterm CBT",
        "instructions": None,
        "duration_minutes": 45,
        "shuffle_questions": True,
        "shuffle_options": True,
        "scheduled_start_at": future_start,
        "latest_normal_start_at": future_start + timedelta(minutes=15),
        "status": ExamStatus.DRAFT,
        "roster_status": ExamRosterStatus.NOT_PREPARED,
        "roster_version": 0,
        "roster_candidate_count": 0,
        "roster_prepared_at": None,
        "roster_error": None,
        "authoring_version": 1,
        "revision_number": 1,
        "revision_of_exam_id": None,
        "created_by_actor_id": LEAD_ACTOR_ID,
        "submitted_by_actor_id": None,
        "submitted_at": None,
        "sealed_by_actor_id": None,
        "sealed_at": None,
        "activated_by_actor_id": None,
        "activated_at": None,
        "closed_by_actor_id": None,
        "closed_at": None,
        "cancelled_by_actor_id": None,
        "cancelled_at": None,
        "cancellation_reason": None,
        "component_maximum_score": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def academic_scope(current_exam: SimpleNamespace) -> dict[str, SimpleNamespace]:
    return {
        "session": SimpleNamespace(id=current_exam.session_id),
        "term": SimpleNamespace(
            id=current_exam.term_id,
            academic_session_id=current_exam.session_id,
        ),
        "scheme": SimpleNamespace(
            id=current_exam.assessment_scheme_id,
            status="active",
        ),
        "component": SimpleNamespace(
            id=current_exam.assessment_component_id,
            assessment_scheme_id=current_exam.assessment_scheme_id,
            is_active=True,
            maximum_score=Decimal("10.00"),
        ),
        "bank": SimpleNamespace(
            id=current_exam.question_bank_id,
            is_active=True,
            curriculum_subject_id=current_exam.curriculum_subject_id,
        ),
    }


class ExamLifecycleSchemaTests(unittest.TestCase):
    def test_invigilator_assignment_accepts_multiple_teacher_ids(self) -> None:
        first = uuid4()
        second = uuid4()
        payload = ExamInvigilatorAssignment(teacher_ids=[first, second])
        self.assertEqual(payload.teacher_ids, [first, second])

    def test_exam_response_exposes_collaboration_and_lifecycle_fields(self) -> None:
        expected = {
            "authoring_version",
            "created_by_actor_id",
            "submitted_by_actor_id",
            "submitted_at",
            "sealed_by_actor_id",
            "sealed_at",
            "activated_by_actor_id",
            "activated_at",
            "closed_by_actor_id",
            "closed_at",
            "cancelled_by_actor_id",
            "cancelled_at",
            "cancellation_reason",
        }
        self.assertTrue(expected.issubset(ExamResponse.model_fields))


class ExamLifecycleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_lead_submit_records_metadata_and_bumps_authoring_version(
        self,
    ) -> None:
        db = AsyncMock()
        current_actor = actor()
        current_exam = exam(status=ExamStatus.DRAFT)
        scope = academic_scope(current_exam)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject_for_term",
                new=AsyncMock(),
            ) as term_authorize,
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                AcademicRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=scope["session"]),
            ),
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(return_value=scope["term"]),
            ),
            patch.object(
                AcademicRepository,
                "get_assessment_scheme_by_id",
                new=AsyncMock(return_value=scope["scheme"]),
            ),
            patch.object(
                AcademicRepository,
                "get_component_by_id",
                new=AsyncMock(return_value=scope["component"]),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=scope["bank"]),
            ),
            patch.object(
                QuestionRepository,
                "count_questions_for_bank",
                new=AsyncMock(return_value=1),
            ),
            patch.object(
                ExamRepository,
                "list_question_selections",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
            patch.object(
                ExamTimetableService,
                "require_planned_slot_available",
                new=AsyncMock(),
            ),
        ):
            result = await ExamService.submit_exam(
                db,
                actor=current_actor,  # type: ignore[arg-type]
                exam_id=current_exam.id,
                expected_authoring_version=1,
            )

        term_authorize.assert_awaited()
        self.assertEqual(result.status, ExamStatus.SUBMITTED)
        self.assertEqual(result.submitted_by_actor_id, current_actor.id)
        self.assertEqual(result.authoring_version, 2)
        db.commit.assert_awaited_once()

    async def test_non_lead_contributor_cannot_submit_shared_paper(self) -> None:
        db = AsyncMock()
        contributor = actor(actor_id=uuid4())
        current_exam = exam(status=ExamStatus.DRAFT)
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            self.assertRaises(ExamAuthorizationError),
        ):
            await ExamService.submit_exam(
                db,
                actor=contributor,  # type: ignore[arg-type]
                exam_id=current_exam.id,
                expected_authoring_version=1,
            )
        db.commit.assert_not_awaited()

    async def test_stale_screen_cannot_submit_shared_paper(self) -> None:
        db = AsyncMock()
        current_exam = exam(status=ExamStatus.DRAFT, authoring_version=5)
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            self.assertRaisesRegex(ExamStateError, "Refresh"),
        ):
            await ExamService.submit_exam(
                db,
                actor=actor(),  # type: ignore[arg-type]
                exam_id=current_exam.id,
                expected_authoring_version=4,
            )

    async def test_admin_return_to_draft_bumps_version_atomically(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(
            status=ExamStatus.SUBMITTED,
            authoring_version=3,
            submitted_by_actor_id=LEAD_ACTOR_ID,
            submitted_at=datetime.now(UTC),
        )
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ) as save_exam,
        ):
            result = await ExamService.return_exam_to_draft(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        self.assertEqual(result.status, ExamStatus.DRAFT)
        self.assertEqual(result.authoring_version, 4)
        self.assertIsNone(result.submitted_by_actor_id)
        self.assertIsNone(result.submitted_at)
        save_exam.assert_awaited_once_with(db, current_exam)
        db.commit.assert_awaited_once()

    async def test_delete_draft_is_lead_or_admin_only(self) -> None:
        db = AsyncMock()
        contributor = actor(actor_id=uuid4())
        current_exam = exam()
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            self.assertRaises(ExamAuthorizationError),
        ):
            await ExamService.delete_draft_exam(
                db,
                actor=contributor,  # type: ignore[arg-type]
                exam_id=current_exam.id,
                expected_authoring_version=1,
            )

    async def test_lead_can_delete_draft_when_still_academically_authorized(
        self,
    ) -> None:
        db = AsyncMock()
        current_actor = actor()
        current_exam = exam()
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject_for_term",
                new=AsyncMock(),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(ExamRepository, "delete_exam", new=AsyncMock()) as delete_exam,
        ):
            await ExamService.delete_draft_exam(
                db,
                actor=current_actor,  # type: ignore[arg-type]
                exam_id=current_exam.id,
                expected_authoring_version=1,
            )

        delete_exam.assert_awaited_once_with(db, current_exam)
        db.commit.assert_awaited_once()

    async def test_seal_uses_full_term_eligibility_not_lead_classes(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(status=ExamStatus.SUBMITTED)
        scope = academic_scope(current_exam)
        source_question = SimpleNamespace(
            id=uuid4(),
            bank_id=current_exam.question_bank_id,
            version=3,
            question_type=QuestionType.SINGLE_CHOICE,
            prompt="2 + 2?",
            instruction=None,
            image_asset_id=None,
        )
        source_option = SimpleNamespace(
            question_id=source_question.id,
            position=1,
            text="4",
            image_asset_id=None,
            is_correct=True,
        )
        first_class = SimpleNamespace(id=uuid4())
        second_class = SimpleNamespace(id=uuid4())
        frozen_id = uuid4()
        order: list[str] = []

        async def record_lock(*_args, **_kwargs):
            order.append("sync_lock")

        async def record_authorize(*_args, **_kwargs):
            order.append("authorize")

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamTimetableService,
                "require_planned_slot_available",
                new=AsyncMock(),
            ),
            patch.object(
                SyncRepository,
                "acquire_apply_lock",
                new=AsyncMock(side_effect=record_lock),
            ),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(side_effect=record_authorize),
            ),
            patch.object(
                AcademicRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=scope["session"]),
            ),
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(return_value=scope["term"]),
            ),
            patch.object(
                AcademicRepository,
                "get_assessment_scheme_by_id",
                new=AsyncMock(return_value=scope["scheme"]),
            ),
            patch.object(
                AcademicRepository,
                "get_component_by_id",
                new=AsyncMock(return_value=scope["component"]),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=scope["bank"]),
            ),
            patch.object(
                ExamRepository,
                "count_exam_questions",
                new=AsyncMock(return_value=0),
            ),
            patch.object(
                ExamService,
                "_resolve_questions_for_sealing",
                new=AsyncMock(return_value=[source_question]),
            ),
            patch.object(
                ExamService,
                "_validate_questions_for_sealing",
                new=AsyncMock(return_value={source_question.id: [source_option]}),
            ),
            patch.object(
                AcademicEligibilityService,
                "list_eligible_classes",
                new=AsyncMock(return_value=[first_class, second_class]),
            ) as eligible,
            patch.object(
                ExamRepository,
                "add_exam_questions",
                new=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            id=frozen_id,
                            source_question_id=source_question.id,
                        )
                    ]
                ),
            ),
            patch.object(ExamRepository, "add_exam_question_options", new=AsyncMock()),
            patch.object(
                ExamRepository, "add_target_classes", new=AsyncMock()
            ) as targets,
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
            patch.object(RuntimeRepository, "add_outbox_event", new=AsyncMock()),
        ):
            result = await ExamService.seal_exam(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        eligible.assert_awaited_once_with(
            db,
            curriculum_subject_id=current_exam.curriculum_subject_id,
            academic_term_id=current_exam.term_id,
        )
        frozen_targets = targets.await_args.args[1]
        self.assertEqual(
            {row.class_id for row in frozen_targets},
            {first_class.id, second_class.id},
        )
        self.assertTrue(
            all(row.teacher_assignment_id is None for row in frozen_targets)
        )
        self.assertLess(order.index("sync_lock"), order.index("authorize"))
        self.assertEqual(result.status, ExamStatus.SEALED)
        self.assertEqual(result.roster_status, ExamRosterStatus.PENDING)

    async def test_seal_rolls_back_if_snapshot_transaction_fails(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(status=ExamStatus.SUBMITTED)
        scope = academic_scope(current_exam)
        source_question = SimpleNamespace(
            id=uuid4(),
            bank_id=current_exam.question_bank_id,
            version=1,
            question_type=QuestionType.SINGLE_CHOICE,
            prompt="Question",
            instruction=None,
            image_asset_id=None,
        )
        option = SimpleNamespace(
            question_id=source_question.id,
            position=1,
            text="Answer",
            image_asset_id=None,
            is_correct=True,
        )
        integrity_error = IntegrityError("insert", {}, Exception("boom"))

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamTimetableService, "require_planned_slot_available", new=AsyncMock()
            ),
            patch.object(SyncRepository, "acquire_apply_lock", new=AsyncMock()),
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                AcademicRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=scope["session"]),
            ),
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(return_value=scope["term"]),
            ),
            patch.object(
                AcademicRepository,
                "get_assessment_scheme_by_id",
                new=AsyncMock(return_value=scope["scheme"]),
            ),
            patch.object(
                AcademicRepository,
                "get_component_by_id",
                new=AsyncMock(return_value=scope["component"]),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(return_value=scope["bank"]),
            ),
            patch.object(
                ExamRepository, "count_exam_questions", new=AsyncMock(return_value=0)
            ),
            patch.object(
                ExamService,
                "_resolve_questions_for_sealing",
                new=AsyncMock(return_value=[source_question]),
            ),
            patch.object(
                ExamService,
                "_validate_questions_for_sealing",
                new=AsyncMock(return_value={source_question.id: [option]}),
            ),
            patch.object(
                AcademicEligibilityService,
                "list_eligible_classes",
                new=AsyncMock(return_value=[SimpleNamespace(id=uuid4())]),
            ),
            patch.object(
                ExamRepository,
                "add_exam_questions",
                new=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            id=uuid4(), source_question_id=source_question.id
                        )
                    ]
                ),
            ),
            patch.object(ExamRepository, "add_exam_question_options", new=AsyncMock()),
            patch.object(
                ExamRepository,
                "add_target_classes",
                new=AsyncMock(side_effect=integrity_error),
            ),
            patch.object(ExamRepository, "save_exam", new=AsyncMock()) as save_exam,
            patch.object(
                RuntimeRepository, "add_outbox_event", new=AsyncMock()
            ) as add_event,
            self.assertRaisesRegex(ValueError, "could not be sealed"),
        ):
            await ExamService.seal_exam(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
        save_exam.assert_not_awaited()
        add_event.assert_not_awaited()

    async def test_assign_invigilator_needs_school_membership_not_subject_assignment(
        self,
    ) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        teacher_id = uuid4()
        current_exam = exam(status=ExamStatus.SEALED)
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                AcademicRepository,
                "list_teachers_by_ids",
                new=AsyncMock(return_value=[SimpleNamespace(id=teacher_id)]),
            ) as teachers,
            patch.object(
                ExamRepository,
                "list_invigilators_for_exam_and_teachers",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                ExamRepository,
                "add_invigilators",
                new=AsyncMock(side_effect=lambda _db, rows: rows),
            ),
        ):
            rows = await ExamService.assign_invigilators(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
                teacher_ids=[teacher_id],
            )

        teachers.assert_awaited_once_with(db, [teacher_id], active_only=True)
        self.assertEqual(len(rows), 1)
        db.commit.assert_awaited_once()

    async def test_activate_requires_ready_roster(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.PENDING,
            sealed_at=datetime.now(UTC),
            component_maximum_score=Decimal("10.00"),
        )
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_latest_child_revision",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                ExamRepository, "count_exam_questions", new=AsyncMock()
            ) as count_questions,
            self.assertRaisesRegex(ExamStateError, "READY"),
        ):
            await ExamService.activate_exam(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        count_questions.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_activate_emits_outbox_event_and_checks_level_free(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.READY,
            sealed_at=datetime.now(UTC),
            component_maximum_score=Decimal("10.00"),
        )
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_latest_child_revision",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                ExamRepository,
                "count_exam_questions",
                new=AsyncMock(return_value=current_exam.question_count),
            ),
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
            patch.object(
                RuntimeRepository, "add_outbox_event", new=AsyncMock()
            ) as add_event,
            patch.object(
                ExamTimetableService, "require_level_free", new=AsyncMock()
            ) as require_level_free,
        ):
            result = await ExamService.activate_exam(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        self.assertEqual(result.status, ExamStatus.ACTIVE)
        require_level_free.assert_awaited_once_with(db, exam_id=current_exam.id)
        self.assertEqual(add_event.await_args.args[1].event_type, "exam.activated")
        db.commit.assert_awaited_once()

    async def test_return_to_draft_is_admin_only(self) -> None:
        db = AsyncMock()
        teacher = actor()
        current_exam = exam(status=ExamStatus.SUBMITTED)
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            self.assertRaises(AcademicAuthorizationError),
        ):
            await ExamService.return_exam_to_draft(
                db,
                actor=teacher,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

    async def test_assign_invigilators_rejects_missing_teacher(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        teacher_id = uuid4()
        current_exam = exam(status=ExamStatus.ACTIVE)
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                AcademicRepository,
                "list_teachers_by_ids",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                ExamRepository, "add_invigilators", new=AsyncMock()
            ) as add_invigilators,
            self.assertRaises(AcademicScopeError),
        ):
            await ExamService.assign_invigilators(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
                teacher_ids=[teacher_id],
            )

        add_invigilators.assert_not_awaited()
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
