from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
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

from app.domains.academics.authorization import (
    AcademicAuthorizationService,
)
from app.domains.exams.exceptions import ExamStateError
from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.models import (
    ExamQuestionSelectionMode,
    ExamRosterStatus,
    ExamStatus,
)
from app.domains.exams.repository import ExamRepository
from app.domains.exams.schemas import (
    ExamQuestionConfiguration,
    ManualQuestionAdd,
)
from app.domains.exams.service import ExamService
from app.domains.exams.timetable_service import ExamTimetableService
from app.domains.questions.repository import QuestionRepository
from app.domains.runtime.repository import RuntimeRepository

LEAD_ID = uuid4()


def actor(*, role: str = "teacher", actor_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=actor_id or (LEAD_ID if role == "teacher" else uuid4()),
        role=role,
        is_active=True,
        weave_membership_id=str(uuid4()) if role == "teacher" else None,
    )


def exam(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "session_id": uuid4(),
        "term_id": uuid4(),
        "curriculum_subject_id": uuid4(),
        "assessment_scheme_id": uuid4(),
        "assessment_component_id": uuid4(),
        "question_bank_id": uuid4(),
        "question_selection_mode": ExamQuestionSelectionMode.RANDOM,
        "question_count": 2,
        "title": "Shared Paper",
        "instructions": None,
        "folder_color": None,
        "duration_minutes": 45,
        "shuffle_questions": True,
        "shuffle_options": True,
        "scheduled_start_at": None,
        "latest_normal_start_at": None,
        "status": ExamStatus.DRAFT,
        "roster_status": ExamRosterStatus.NOT_PREPARED,
        "roster_version": 0,
        "roster_candidate_count": 0,
        "roster_prepared_at": None,
        "roster_error": None,
        "authoring_version": 1,
        "revision_number": 1,
        "revision_of_exam_id": None,
        "created_by_actor_id": LEAD_ID,
        "component_maximum_score": None,
        "sealed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ExamRegressionCoverageTests(unittest.IsolatedAsyncioTestCase):
    async def test_lead_can_confirm_destructive_manual_to_random_change(self) -> None:
        db = AsyncMock()
        current_exam = exam(
            question_selection_mode=ExamQuestionSelectionMode.MANUAL,
            question_count=3,
        )
        new_bank_id = uuid4()
        existing = [
            SimpleNamespace(
                question_id=uuid4(),
                position=1,
                added_by_actor_id=LEAD_ID,
            )
        ]
        payload = ExamQuestionConfiguration(
            question_bank_id=new_bank_id,
            question_selection_mode=ExamQuestionSelectionMode.RANDOM,
            question_count=2,
            clear_existing_manual_selections=True,
            expected_authoring_version=1,
        )

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
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=new_bank_id,
                        is_active=True,
                        curriculum_subject_id=current_exam.curriculum_subject_id,
                    )
                ),
            ),
            patch.object(
                ExamRepository,
                "list_question_selections",
                new=AsyncMock(return_value=existing),
            ),
            patch.object(
                QuestionRepository,
                "count_questions_for_bank",
                new=AsyncMock(return_value=2),
            ),
            patch.object(
                ExamRepository, "clear_question_selections", new=AsyncMock()
            ) as clear,
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            result = await ExamService.configure_questions(
                db,
                actor=actor(),  # type: ignore[arg-type]
                exam_id=current_exam.id,
                payload=payload,
            )

        clear.assert_awaited_once_with(db, current_exam.id)
        self.assertEqual(result.question_bank_id, new_bank_id)
        self.assertEqual(
            result.question_selection_mode, ExamQuestionSelectionMode.RANDOM
        )
        self.assertEqual(result.authoring_version, 2)
        db.commit.assert_awaited_once()

    async def test_contributor_cannot_add_question_from_another_bank(self) -> None:
        db = AsyncMock()
        contributor = actor(actor_id=uuid4())
        current_exam = exam(
            question_selection_mode=ExamQuestionSelectionMode.MANUAL,
            question_count=3,
        )
        question_id = uuid4()
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
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=current_exam.question_bank_id,
                        is_active=True,
                        curriculum_subject_id=current_exam.curriculum_subject_id,
                    )
                ),
            ),
            patch.object(
                ExamRepository,
                "list_question_selections",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                QuestionRepository,
                "list_questions_by_ids",
                new=AsyncMock(
                    return_value=[SimpleNamespace(id=question_id, bank_id=uuid4())]
                ),
            ),
            patch.object(
                ExamRepository, "add_question_selections", new=AsyncMock()
            ) as add,
            self.assertRaisesRegex(ValueError, "examination question bank"),
        ):
            await ExamService.add_manual_questions(
                db,
                actor=contributor,  # type: ignore[arg-type]
                exam_id=current_exam.id,
                payload=ManualQuestionAdd(question_ids=[question_id]),
            )

        add.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_manual_sealing_preserves_selection_order_and_row_lock(self) -> None:
        db = AsyncMock()
        first_id = uuid4()
        second_id = uuid4()
        current_exam = exam(
            status=ExamStatus.SUBMITTED,
            question_selection_mode=ExamQuestionSelectionMode.MANUAL,
            question_count=2,
        )
        selections = [
            SimpleNamespace(
                question_id=first_id, position=1, added_by_actor_id=LEAD_ID
            ),
            SimpleNamespace(
                question_id=second_id, position=2, added_by_actor_id=uuid4()
            ),
        ]
        first = SimpleNamespace(id=first_id)
        second = SimpleNamespace(id=second_id)
        with (
            patch.object(
                ExamRepository,
                "list_question_selections",
                new=AsyncMock(return_value=selections),
            ),
            patch.object(
                QuestionRepository,
                "list_questions_by_ids",
                new=AsyncMock(return_value=[second, first]),
            ) as list_questions,
        ):
            resolved = await ExamService._resolve_questions_for_sealing(
                db,
                exam=current_exam,
            )

        self.assertEqual([row.id for row in resolved], [first_id, second_id])
        list_questions.assert_awaited_once_with(
            db,
            [first_id, second_id],
            active_only=True,
            lock=True,
        )

    async def test_revision_creation_rejects_non_revisionable_leaf_states(self) -> None:
        admin = actor(role="admin")
        for lifecycle_status in (
            ExamStatus.ACTIVE,
            ExamStatus.SUSPENDED,
        ):
            with self.subTest(status=lifecycle_status):
                db = AsyncMock()
                current_exam = exam(status=lifecycle_status)
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
                    self.assertRaisesRegex(
                        ExamStateError, "latest SEALED or CANCELLED"
                    ),
                ):
                    await ExamService.create_revision(
                        db,
                        actor=admin,  # type: ignore[arg-type]
                        exam_id=current_exam.id,
                    )
                db.commit.assert_not_awaited()

    async def test_closed_revision_requires_voided_results(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(status=ExamStatus.CLOSED)

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
                ExamExecutionService,
                "results_are_voided",
                new=AsyncMock(return_value=False),
            ),
            self.assertRaisesRegex(ExamStateError, "results are voided"),
        ):
            await ExamService.create_revision(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        db.commit.assert_not_awaited()

    async def test_closed_revision_denies_unaccepted_or_unknown_decisions(self) -> None:
        for disposition in (
            None,
            ExamResultDisposition.PENDING_REVIEW,
            ExamResultDisposition.APPROVED,
        ):
            with self.subTest(disposition=disposition):
                db = AsyncMock()
                original = exam(status=ExamStatus.CLOSED)
                control = (
                    SimpleNamespace(result_disposition=disposition)
                    if disposition
                    else None
                )
                with (
                    patch.object(
                        ExamRepository,
                        "get_exam_by_id",
                        new=AsyncMock(return_value=original),
                    ),
                    patch.object(
                        ExamRepository,
                        "get_latest_child_revision",
                        new=AsyncMock(return_value=None),
                    ),
                    patch.object(
                        ExamExecutionRepository,
                        "get_control",
                        new=AsyncMock(return_value=control),
                    ),
                    self.assertRaisesRegex(ExamStateError, "results are voided"),
                ):
                    await ExamService.create_revision(
                        db, actor=actor(role="admin"), exam_id=original.id
                    )
                db.commit.assert_not_awaited()
                self.assertEqual(original.status, ExamStatus.CLOSED)

    async def test_closed_voided_revision_creates_draft_without_reopening_history(
        self,
    ) -> None:
        db = AsyncMock()
        original = exam(status=ExamStatus.CLOSED)
        with (
            patch.object(
                ExamRepository, "get_exam_by_id", new=AsyncMock(return_value=original)
            ),
            patch.object(
                ExamRepository,
                "get_latest_child_revision",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                ExamExecutionService,
                "results_are_voided",
                new=AsyncMock(return_value=True),
            ) as voided,
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "add_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            revision = await ExamService.create_revision(
                db, actor=actor(role="admin"), exam_id=original.id
            )
        voided.assert_awaited_once_with(db, exam_id=original.id)
        self.assertEqual(original.status, ExamStatus.CLOSED)
        self.assertEqual(original.revision_number, 1)
        self.assertEqual(revision.status, ExamStatus.DRAFT)
        self.assertEqual(revision.revision_number, 2)
        self.assertEqual(revision.revision_of_exam_id, original.id)
        self.assertEqual(revision.term_id, original.term_id)
        self.assertEqual(revision.curriculum_subject_id, original.curriculum_subject_id)
        self.assertEqual(
            revision.assessment_component_id, original.assessment_component_id
        )

    async def test_cancelled_leaf_can_create_next_shared_revision(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(
            status=ExamStatus.CANCELLED,
            revision_number=2,
            revision_of_exam_id=uuid4(),
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
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "add_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            revision = await ExamService.create_revision(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        self.assertEqual(revision.status, ExamStatus.DRAFT)
        self.assertEqual(revision.revision_number, 3)
        self.assertEqual(revision.revision_of_exam_id, current_exam.id)
        db.commit.assert_awaited_once()

    async def test_activate_rejects_non_latest_revision(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(
            status=ExamStatus.SEALED,
            roster_status=ExamRosterStatus.READY,
            sealed_at=datetime.now(UTC),
            component_maximum_score=10,
        )
        child = exam(
            status=ExamStatus.DRAFT,
            revision_number=2,
            revision_of_exam_id=current_exam.id,
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
                new=AsyncMock(side_effect=[child, None]),
            ),
            patch.object(
                ExamRepository, "count_exam_questions", new=AsyncMock()
            ) as count_questions,
            self.assertRaisesRegex(ExamStateError, "latest examination revision"),
        ):
            await ExamService.activate_exam(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        count_questions.assert_not_awaited()

    async def test_suspended_close_and_cancel_require_open_suspension(self) -> None:
        admin = actor(role="admin")
        for operation in ("close", "cancel"):
            db = AsyncMock()
            current_exam = exam(status=ExamStatus.SUSPENDED)
            with (
                patch.object(
                    ExamRepository,
                    "get_exam_by_id",
                    new=AsyncMock(return_value=current_exam),
                ),
                patch.object(
                    ExamRepository,
                    "get_open_suspension_for_exam",
                    new=AsyncMock(return_value=None),
                ),
                self.assertRaisesRegex(ExamStateError, "no open suspension"),
            ):
                if operation == "close":
                    await ExamService.close_exam(
                        db,
                        actor=admin,  # type: ignore[arg-type]
                        exam_id=current_exam.id,
                    )
                else:
                    await ExamService.cancel_exam(
                        db,
                        actor=admin,  # type: ignore[arg-type]
                        exam_id=current_exam.id,
                        reason="Invalid sitting",
                    )
            db.commit.assert_not_awaited()

    async def test_close_rolls_back_if_suspension_save_fails(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(status=ExamStatus.SUSPENDED)
        suspension = SimpleNamespace(
            resumed_at=None,
            resumed_by_actor_id=None,
            resume_reason=None,
        )
        error = IntegrityError("update", {}, Exception("boom"))
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_open_suspension_for_exam",
                new=AsyncMock(return_value=suspension),
            ),
            patch.object(
                ExamRepository, "save_suspension", new=AsyncMock(side_effect=error)
            ),
            patch.object(ExamRepository, "save_exam", new=AsyncMock()) as save_exam,
            self.assertRaisesRegex(ValueError, "could not be closed"),
        ):
            await ExamService.close_exam(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
            )

        db.rollback.assert_awaited_once()
        save_exam.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_resume_checks_level_is_free_before_reactivation(self) -> None:
        db = AsyncMock()
        admin = actor(role="admin")
        current_exam = exam(status=ExamStatus.SUSPENDED)
        suspension = SimpleNamespace(
            resumed_at=None,
            resumed_by_actor_id=None,
            resume_reason=None,
        )
        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=current_exam),
            ),
            patch.object(
                ExamRepository,
                "get_open_suspension_for_exam",
                new=AsyncMock(return_value=suspension),
            ),
            patch.object(ExamRepository, "save_suspension", new=AsyncMock()),
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
            patch.object(RuntimeRepository, "add_outbox_event", new=AsyncMock()),
            patch.object(
                ExamTimetableService, "require_level_free", new=AsyncMock()
            ) as level_free,
        ):
            result = await ExamService.resume_exam(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=current_exam.id,
                reason="Recovered",
            )

        self.assertEqual(result.status, ExamStatus.ACTIVE)
        level_free.assert_awaited_once_with(db, exam_id=current_exam.id)
        self.assertEqual(suspension.resume_reason, "Recovered")


if __name__ == "__main__":
    unittest.main()
