from __future__ import annotations

import os
import unittest
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
from app.domains.exams.models import ExamQuestionSelectionMode
from app.domains.exams.repository import ExamRepository
from app.domains.exams.schemas import ExamCreate
from app.domains.exams.service import ExamService
from app.domains.questions.repository import QuestionRepository


def actor(*, role: str, teacher_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        role=role,
        is_active=True,
        weave_membership_id=str(teacher_id) if teacher_id is not None else None,
    )


def payload(*, lead_teacher_id: UUID | None = None) -> ExamCreate:
    return ExamCreate(
        session_id=uuid4(),
        term_id=uuid4(),
        curriculum_subject_id=uuid4(),
        assessment_scheme_id=uuid4(),
        assessment_component_id=uuid4(),
        question_bank_id=uuid4(),
        question_selection_mode=ExamQuestionSelectionMode.MANUAL,
        question_count=20,
        title="English CA 1",
        duration_minutes=45,
        lead_teacher_id=lead_teacher_id,
    )


class AtomicExamLeadCreationTests(unittest.IsolatedAsyncioTestCase):
    async def _create_with_mocks(
        self,
        *,
        current_actor: SimpleNamespace,
        current_payload: ExamCreate,
    ):
        db = AsyncMock()
        added = []

        async def add_exam(_db, row):
            added.append(row)
            return row

        with (
            patch.object(
                AcademicRepository,
                "get_session_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=current_payload.session_id)
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=current_payload.term_id,
                        academic_session_id=current_payload.session_id,
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
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=current_payload.assessment_scheme_id
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_component_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=current_payload.assessment_component_id,
                        assessment_scheme_id=current_payload.assessment_scheme_id,
                    )
                ),
            ),
            patch.object(
                QuestionRepository,
                "get_bank_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=current_payload.question_bank_id,
                        is_active=True,
                        curriculum_subject_id=current_payload.curriculum_subject_id,
                    )
                ),
            ),
            patch.object(
                ExamRepository,
                "get_exam_revision",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                ExamService,
                "_before_create_exam_save",
                new=AsyncMock(),
            ),
            patch.object(
                ExamRepository,
                "add_exam",
                new=AsyncMock(side_effect=add_exam),
            ),
        ):
            result = await ExamService.create_exam(
                db,
                actor=current_actor,  # type: ignore[arg-type]
                payload=current_payload,
            )

        self.assertEqual(len(added), 1)
        db.commit.assert_awaited_once()
        return result

    async def test_admin_selected_teacher_is_persisted_on_initial_insert(self) -> None:
        admin = actor(role="admin")
        lead_teacher_id = uuid4()
        current_payload = payload(lead_teacher_id=lead_teacher_id)

        with patch.object(
            ExamService,
            "_validate_lead_teacher",
            new=AsyncMock(),
        ) as validate:
            exam = await self._create_with_mocks(
                current_actor=admin,
                current_payload=current_payload,
            )

        validate.assert_awaited_once_with(
            unittest.mock.ANY,
            teacher_id=lead_teacher_id,
            curriculum_subject_id=current_payload.curriculum_subject_id,
            term_id=current_payload.term_id,
        )
        self.assertEqual(exam.created_by_actor_id, admin.id)
        self.assertEqual(exam.lead_teacher_id, lead_teacher_id)
        self.assertEqual(exam.lead_assigned_by_actor_id, admin.id)
        self.assertIsNotNone(exam.lead_assigned_at)

    async def test_teacher_created_paper_persists_teacher_as_lead(self) -> None:
        teacher_id = uuid4()
        teacher = actor(role="teacher", teacher_id=teacher_id)
        current_payload = payload()

        exam = await self._create_with_mocks(
            current_actor=teacher,
            current_payload=current_payload,
        )

        self.assertEqual(exam.created_by_actor_id, teacher.id)
        self.assertEqual(exam.lead_teacher_id, teacher_id)
        self.assertEqual(exam.lead_assigned_by_actor_id, teacher.id)
        self.assertIsNotNone(exam.lead_assigned_at)


if __name__ == "__main__":
    unittest.main()
