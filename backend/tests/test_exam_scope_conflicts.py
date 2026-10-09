from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

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
from app.domains.exams.models import ExamQuestionSelectionMode, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.exams.schemas import ExamCreate
from app.domains.exams.service import ExamService
from app.domains.questions.repository import QuestionRepository


class ExamScopeConflictMessageTests(unittest.TestCase):
    def test_conflict_messages_explain_the_blocking_lifecycle_state(self) -> None:
        cases = {
            ExamStatus.DRAFT: "continue editing the existing draft",
            ExamStatus.SUBMITTED: "submitted for review",
            ExamStatus.SEALED: "sealed as the official paper",
            ExamStatus.ACTIVE: "currently active",
            ExamStatus.SUSPENDED: "currently suspended",
            ExamStatus.CLOSED: "already been conducted and closed",
            ExamStatus.CANCELLED: "cancelled but its exam lineage is preserved",
        }

        for status, expected_text in cases.items():
            with self.subTest(status=status):
                existing = SimpleNamespace(title="Existing CA 1", status=status)
                message = ExamService._exam_creation_conflict_message(existing)
                self.assertIn("Existing CA 1", message)
                self.assertIn(expected_text, message)
                self.assertIn(
                    "term, curriculum subject and assessment component",
                    message,
                )

    def test_closed_conflict_explains_makeup_and_replacement_paths(self) -> None:
        existing = SimpleNamespace(
            title="Mathematics CA 1",
            status=ExamStatus.CLOSED,
        )

        message = ExamService._exam_creation_conflict_message(existing)

        self.assertIn("makeup/late-start", message)
        self.assertIn("results must first be voided", message)
        self.assertIn("revision/replacement workflow", message)


class ExamScopeCreationTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_scope_is_blocked_even_when_new_title_is_different(self) -> None:
        db = AsyncMock()
        actor = SimpleNamespace(
            id=uuid4(),
            role="admin",
            is_active=True,
            weave_membership_id=None,
        )
        session_id = uuid4()
        term_id = uuid4()
        subject_id = uuid4()
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
            question_selection_mode=ExamQuestionSelectionMode.MANUAL,
            question_count=20,
            title="A completely different title",
            duration_minutes=45,
        )
        existing = SimpleNamespace(
            id=uuid4(),
            title="Original Mathematics CA 1",
            status=ExamStatus.CLOSED,
        )

        with (
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
                AcademicAuthorizationService,
                "require_can_author_curriculum_subject_for_term",
                new=AsyncMock(),
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
                ExamRepository,
                "get_exam_revision",
                new=AsyncMock(return_value=existing),
            ) as get_revision,
            patch.object(ExamRepository, "add_exam", new=AsyncMock()) as add_exam,
            self.assertRaisesRegex(ValueError, "already been conducted and closed"),
        ):
            await ExamService.create_exam(
                db,
                actor=actor,  # type: ignore[arg-type]
                payload=payload,
            )

        get_revision.assert_awaited_once_with(
            db,
            term_id=term_id,
            curriculum_subject_id=subject_id,
            assessment_component_id=component_id,
            title=payload.title,
            revision_number=1,
        )
        add_exam.assert_not_awaited()
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
