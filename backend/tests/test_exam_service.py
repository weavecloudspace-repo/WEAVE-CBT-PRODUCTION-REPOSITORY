from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DEBUG"] = "false"

from app.domains.academics.authorization import (
    AcademicAuthorizationService,
)
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
    ExamCreate,
    ExamQuestionConfiguration,
    ExamUpdate,
    ManualQuestionAdd,
    ManualQuestionRemove,
    ManualQuestionReorder,
)
from app.domains.exams.service import ExamService
from app.domains.questions.repository import QuestionRepository

LEAD_ACTOR_ID = uuid4()


def actor(*, role: str = "teacher", actor_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=actor_id or (LEAD_ACTOR_ID if role == "teacher" else uuid4()),
        role=role,
        is_active=True,
        weave_membership_id=str(uuid4()) if role == "teacher" else None,
    )


def draft_exam(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "session_id": uuid4(),
        "term_id": uuid4(),
        "curriculum_subject_id": uuid4(),
        "assessment_scheme_id": uuid4(),
        "assessment_component_id": uuid4(),
        "question_bank_id": uuid4(),
        "question_selection_mode": ExamQuestionSelectionMode.RANDOM,
        "question_count": 20,
        "title": "Midterm CBT",
        "instructions": None,
        "duration_minutes": 45,
        "shuffle_questions": True,
        "shuffle_options": True,
        "scheduled_start_at": None,
        "latest_normal_start_at": None,
        "status": ExamStatus.DRAFT,
        "roster_status": ExamRosterStatus.NOT_PREPARED,
        "roster_version": 0,
        "roster_candidate_count": 0,
        "authoring_version": 1,
        "revision_number": 1,
        "revision_of_exam_id": None,
        "created_by_actor_id": LEAD_ACTOR_ID,
        "component_maximum_score": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ExamSchemaValidationTests(unittest.TestCase):
    def test_update_rejects_invalid_window_when_both_fields_are_supplied(self) -> None:
        start_at = datetime.now(UTC) + timedelta(days=1)
        with self.assertRaisesRegex(
            ValueError, "Normal entry deadline must be later"
        ):
            ExamUpdate(
                scheduled_start_at=start_at,
                latest_normal_start_at=start_at - timedelta(minutes=1),
            )

    def test_authoring_mutations_start_with_version_one(self) -> None:
        self.assertEqual(ExamUpdate().expected_authoring_version, 1)
        self.assertEqual(
            ManualQuestionAdd(question_ids=[uuid4()]).expected_authoring_version,
            1,
        )

    def test_manual_question_payloads_reject_duplicate_ids(self) -> None:
        question_id = uuid4()
        with self.assertRaisesRegex(ValueError, "duplicate questions"):
            ManualQuestionAdd(question_ids=[question_id, question_id])
        with self.assertRaisesRegex(ValueError, "duplicate questions"):
            ManualQuestionReorder(question_ids=[question_id, question_id])

    def test_question_configuration_does_not_confirm_destructive_clear_by_default(
        self,
    ) -> None:
        payload = ExamQuestionConfiguration(
            question_bank_id=uuid4(),
            question_selection_mode=ExamQuestionSelectionMode.RANDOM,
            question_count=20,
        )
        self.assertFalse(payload.clear_existing_manual_selections)
        self.assertEqual(payload.expected_authoring_version, 1)


class ExamServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_random_exam_requires_enough_active_questions(self) -> None:
        db = AsyncMock()
        current_actor = actor()
        subject_id = uuid4()
        session_id = uuid4()
        term_id = uuid4()
        scheme_id = uuid4()
        component_id = uuid4()
        bank_id = uuid4()
        payload = ExamCreate(
            session_id=session_id,
            term_id=term_id,
            curriculum_subject_id=subject_id,
            assessment_scheme_id=scheme_id,
            assessment_component_id=component_id,
            question_bank_id=bank_id,
            question_selection_mode=ExamQuestionSelectionMode.RANDOM,
            question_count=20,
            title="First CA",
            duration_minutes=45,
        )

        with (
            patch.object(
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject_for_term",
                new=AsyncMock(),
            ) as authorize,
            patch.object(
                AcademicRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=SimpleNamespace(id=session_id)),
            ),
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=term_id, academic_session_id=session_id
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_assessment_scheme_by_id",
                new=AsyncMock(return_value=SimpleNamespace(id=scheme_id)),
            ),
            patch.object(
                AcademicRepository,
                "get_component_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=component_id, assessment_scheme_id=scheme_id
                    )
                ),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=bank_id, is_active=True, curriculum_subject_id=subject_id
                    )
                ),
            ),
            patch.object(
                QuestionRepository,
                "count_questions_for_bank",
                new=AsyncMock(return_value=19),
            ) as count_questions,
            patch.object(
                ExamRepository, "get_exam_revision", new=AsyncMock()
            ) as revision,
            patch.object(ExamRepository, "add_exam", new=AsyncMock()) as add_exam,
        ):
            with self.assertRaisesRegex(ValueError, "enough active questions"):
                await ExamService.create_exam(db, actor=current_actor, payload=payload)  # type: ignore[arg-type]

        authorize.assert_awaited_once_with(
            db,
            actor=current_actor,
            curriculum_subject_id=subject_id,
            academic_term_id=term_id,
        )
        count_questions.assert_awaited_once_with(db, bank_id, active_only=True)
        revision.assert_not_awaited()
        add_exam.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_update_merges_existing_schedule_before_validating_window(
        self,
    ) -> None:
        db = AsyncMock()
        current_actor = actor()
        start_at = datetime.now(UTC) + timedelta(days=1)
        current_exam = draft_exam(
            scheduled_start_at=start_at, latest_normal_start_at=None
        )
        payload = ExamUpdate(
            expected_authoring_version=1,
            latest_normal_start_at=start_at,
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
                AcademicRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=SimpleNamespace(id=current_exam.session_id)),
            ),
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=current_exam.term_id,
                        academic_session_id=current_exam.session_id,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_assessment_scheme_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=current_exam.assessment_scheme_id)
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_component_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=current_exam.assessment_component_id,
                        assessment_scheme_id=current_exam.assessment_scheme_id,
                    )
                ),
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
            patch.object(ExamRepository, "save_exam", new=AsyncMock()) as save_exam,
        ):
            with self.assertRaisesRegex(
                ExamStateError, "must be later than the scheduled start"
            ):
                await ExamService.update_exam(
                    db, actor=current_actor, payload=payload, exam_id=current_exam.id
                )  # type: ignore[arg-type]

        save_exam.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_non_lead_contributor_cannot_change_global_exam_settings(
        self,
    ) -> None:
        db = AsyncMock()
        contributor = actor(actor_id=uuid4())
        current_exam = draft_exam()
        with patch.object(
            ExamRepository, "get_exam_by_id", new=AsyncMock(return_value=current_exam)
        ), self.assertRaises(ExamAuthorizationError):
            await ExamService.update_exam(
                db,
                actor=contributor,
                payload=ExamUpdate(title="Changed"),
                exam_id=current_exam.id,
            )  # type: ignore[arg-type]

    async def test_stale_authoring_version_rejects_mutation(self) -> None:
        db = AsyncMock()
        current_exam = draft_exam(authoring_version=4)
        with patch.object(
            ExamRepository, "get_exam_by_id", new=AsyncMock(return_value=current_exam)
        ), self.assertRaisesRegex(ExamStateError, "Refresh"):
            await ExamService.update_exam(
                db,
                actor=actor(),
                payload=ExamUpdate(expected_authoring_version=3, title="Changed"),
                exam_id=current_exam.id,
            )  # type: ignore[arg-type]

    async def test_configure_questions_is_lead_controlled(self) -> None:
        db = AsyncMock()
        contributor = actor(actor_id=uuid4())
        current_exam = draft_exam(
            question_selection_mode=ExamQuestionSelectionMode.MANUAL, question_count=3
        )
        payload = ExamQuestionConfiguration(
            question_bank_id=current_exam.question_bank_id,
            question_selection_mode=ExamQuestionSelectionMode.RANDOM,
            question_count=2,
        )
        with patch.object(
            ExamRepository, "get_exam_by_id", new=AsyncMock(return_value=current_exam)
        ), self.assertRaises(ExamAuthorizationError):
            await ExamService.configure_questions(
                db, actor=contributor, exam_id=current_exam.id, payload=payload
            )  # type: ignore[arg-type]

    async def test_lead_configuration_preserves_destructive_confirmation_guard(
        self,
    ) -> None:
        db = AsyncMock()
        current_exam = draft_exam(
            question_selection_mode=ExamQuestionSelectionMode.MANUAL, question_count=3
        )
        payload = ExamQuestionConfiguration(
            question_bank_id=current_exam.question_bank_id,
            question_selection_mode=ExamQuestionSelectionMode.RANDOM,
            question_count=2,
        )
        selections = [
            SimpleNamespace(
                question_id=uuid4(), position=1, added_by_actor_id=LEAD_ACTOR_ID
            )
        ]
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
                new=AsyncMock(return_value=selections),
            ),self.assertRaisesRegex(
            ValueError, "clear_existing_manual_selections=true"
        )
        ):
            await ExamService.configure_questions(
                db, actor=actor(), exam_id=current_exam.id, payload=payload
            )  # type: ignore[arg-type]

    async def test_second_eligible_teacher_can_contribute_and_is_recorded(self) -> None:
        db = AsyncMock()
        contributor = actor(actor_id=uuid4())
        current_exam = draft_exam(
            question_selection_mode=ExamQuestionSelectionMode.MANUAL, question_count=3
        )
        question_id = uuid4()
        payload = ManualQuestionAdd(
            question_ids=[question_id], expected_authoring_version=1
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
            ) as authorize,
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
                    return_value=[
                        SimpleNamespace(
                            id=question_id, bank_id=current_exam.question_bank_id
                        )
                    ]
                ),
            ),
            patch.object(
                ExamRepository,
                "add_question_selections",
                new=AsyncMock(side_effect=lambda _db, rows: rows),
            ) as add_selections,
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ),
        ):
            result = await ExamService.add_manual_questions(
                db, actor=contributor, exam_id=current_exam.id, payload=payload
            )  # type: ignore[arg-type]
        authorize.assert_awaited_once_with(
            db,
            actor=contributor,
            curriculum_subject_id=current_exam.curriculum_subject_id,
            academic_term_id=current_exam.term_id,
        )
        added = add_selections.await_args.args[1]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].added_by_actor_id, contributor.id)
        self.assertEqual(result.authoring_version, 2)
        db.commit.assert_awaited_once()

    async def test_contributor_cannot_remove_another_teachers_question(self) -> None:
        db = AsyncMock()
        contributor = actor(actor_id=uuid4())
        current_exam = draft_exam(
            question_selection_mode=ExamQuestionSelectionMode.MANUAL
        )
        question_id = uuid4()
        selection = SimpleNamespace(
            question_id=question_id,
            position=1,
            added_by_actor_id=uuid4(),
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
                ExamRepository,
                "get_question_selection",
                new=AsyncMock(return_value=selection),
            ) as get_selection,
            patch.object(
                ExamRepository, "clear_question_selections", new=AsyncMock()
            ) as clear_selections,
            patch.object(ExamRepository, "save_exam", new=AsyncMock()) as save_exam,
        ):
            with self.assertRaisesRegex(
                ExamAuthorizationError, "only questions they added"
            ):
                await ExamService.remove_manual_question(
                    db,
                    actor=contributor,  # type: ignore[arg-type]
                    exam_id=current_exam.id,
                    payload=ManualQuestionRemove(question_id=question_id),
                )

        get_selection.assert_awaited_once_with(
            db,
            exam_id=current_exam.id,
            question_id=question_id,
            lock=True,
        )
        clear_selections.assert_not_awaited()
        save_exam.assert_not_awaited()
        db.commit.assert_not_awaited()
        self.assertEqual(current_exam.authoring_version, 1)


if __name__ == "__main__":
    unittest.main()
