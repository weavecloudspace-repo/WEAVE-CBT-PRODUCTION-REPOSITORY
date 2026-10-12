from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DEBUG"] = "false"

from app.domains.exams.exceptions import (
    ExamAuthorizationError,
    ExamStateError,
)
from app.domains.exams.models import Exam, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.exams.router import router
from app.domains.exams.schemas import (
    ExamCreate,
    ExamLeadAssignment,
    ExamResponse,
)
from app.domains.exams.service import ExamService


def make_actor(
    *,
    role: str,
    actor_id: UUID | None = None,
    teacher_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=actor_id or uuid4(),
        role=role,
        is_active=True,
        weave_membership_id=str(teacher_id or uuid4()) if role == "teacher" else None,
    )


def make_exam(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "status": ExamStatus.DRAFT,
        "authoring_version": 3,
        "curriculum_subject_id": uuid4(),
        "term_id": uuid4(),
        "created_by_actor_id": uuid4(),
        "lead_teacher_id": None,
        "lead_assigned_by_actor_id": uuid4(),
        "lead_assigned_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_create_payload(*, lead_teacher_id: UUID | None = None) -> ExamCreate:
    return ExamCreate(
        session_id=uuid4(),
        term_id=uuid4(),
        curriculum_subject_id=uuid4(),
        assessment_scheme_id=uuid4(),
        assessment_component_id=uuid4(),
        question_bank_id=uuid4(),
        question_count=20,
        title="English CA 1",
        duration_minutes=45,
        lead_teacher_id=lead_teacher_id,
    )


class ExamLeadContractTests(unittest.TestCase):
    def test_exam_persists_creator_and_lead_separately(self) -> None:
        self.assertIn("created_by_actor_id", Exam.__table__.c)
        self.assertIn("lead_teacher_id", Exam.__table__.c)
        self.assertIn("lead_assigned_by_actor_id", Exam.__table__.c)
        self.assertIn("lead_assigned_at", Exam.__table__.c)
        self.assertTrue(Exam.__table__.c.lead_teacher_id.nullable)
        self.assertIn("lead_teacher_id", ExamResponse.model_fields)
        self.assertIn("lead_assigned_at", ExamResponse.model_fields)

    def test_lead_assignment_schema_supports_admin_led_paper(self) -> None:
        payload = ExamLeadAssignment(expected_authoring_version=4)
        self.assertIsNone(payload.lead_teacher_id)
        self.assertEqual(payload.expected_authoring_version, 4)

    def test_router_exposes_lead_candidate_and_assignment_routes(self) -> None:
        candidates = next(
            route
            for route in router.routes
            if getattr(route, "path", None) == "/exams/lead-candidates"
            and "GET" in getattr(route, "methods", set())
        )
        assignment = next(
            route
            for route in router.routes
            if getattr(route, "path", None) == "/exams/{exam_id}/lead"
            and "PUT" in getattr(route, "methods", set())
        )
        self.assertIsNotNone(candidates)
        self.assertIsNotNone(assignment)


class ExamLeadPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_teacher_creator_automatically_resolves_to_self_as_lead(self) -> None:
        db = AsyncMock()
        teacher_id = uuid4()
        teacher = make_actor(role="teacher", teacher_id=teacher_id)
        payload = make_create_payload()

        resolved = await ExamService._resolve_initial_lead_teacher_id(
            db,
            actor=teacher,  # type: ignore[arg-type]
            payload=payload,
        )

        self.assertEqual(resolved, teacher_id)

    async def test_teacher_cannot_nominate_another_teacher_at_creation(self) -> None:
        db = AsyncMock()
        teacher = make_actor(role="teacher", teacher_id=uuid4())
        payload = make_create_payload(lead_teacher_id=uuid4())

        with self.assertRaisesRegex(ExamAuthorizationError, "creating teacher"):
            await ExamService._resolve_initial_lead_teacher_id(
                db,
                actor=teacher,  # type: ignore[arg-type]
                payload=payload,
            )

    async def test_admin_may_create_admin_led_paper(self) -> None:
        db = AsyncMock()
        admin = make_actor(role="admin")
        payload = make_create_payload()

        with patch.object(
            ExamService,
            "_validate_lead_teacher",
            new=AsyncMock(),
        ) as validate:
            resolved = await ExamService._resolve_initial_lead_teacher_id(
                db,
                actor=admin,  # type: ignore[arg-type]
                payload=payload,
            )

        self.assertIsNone(resolved)
        validate.assert_not_awaited()

    async def test_admin_selected_lead_is_validated_against_academic_scope(
        self,
    ) -> None:
        db = AsyncMock()
        admin = make_actor(role="admin")
        selected_teacher = uuid4()
        payload = make_create_payload(lead_teacher_id=selected_teacher)

        with patch.object(
            ExamService,
            "_validate_lead_teacher",
            new=AsyncMock(),
        ) as validate:
            resolved = await ExamService._resolve_initial_lead_teacher_id(
                db,
                actor=admin,  # type: ignore[arg-type]
                payload=payload,
            )

        self.assertEqual(resolved, selected_teacher)
        validate.assert_awaited_once_with(
            db,
            teacher_id=selected_teacher,
            curriculum_subject_id=payload.curriculum_subject_id,
            term_id=payload.term_id,
        )

    def test_explicit_lead_authority_is_independent_of_creator(self) -> None:
        creator_actor_id = uuid4()
        lead_teacher_id = uuid4()
        lead = make_actor(
            role="teacher",
            actor_id=uuid4(),
            teacher_id=lead_teacher_id,
        )
        creator = make_actor(
            role="teacher",
            actor_id=creator_actor_id,
            teacher_id=uuid4(),
        )
        exam = make_exam(
            created_by_actor_id=creator_actor_id,
            lead_teacher_id=lead_teacher_id,
        )

        self.assertTrue(ExamService._is_lead_or_admin(lead, exam))
        self.assertFalse(ExamService._is_lead_or_admin(creator, exam))

    def test_explicit_admin_led_paper_does_not_fall_back_to_teacher_creator(
        self,
    ) -> None:
        creator_actor_id = uuid4()
        creator = make_actor(
            role="teacher",
            actor_id=creator_actor_id,
            teacher_id=uuid4(),
        )
        exam = make_exam(
            created_by_actor_id=creator_actor_id,
            lead_teacher_id=None,
            lead_assigned_at=datetime.now(UTC),
        )

        self.assertFalse(ExamService._is_lead_or_admin(creator, exam))

    def test_admin_always_retains_supervisory_override(self) -> None:
        exam = make_exam(lead_teacher_id=uuid4())
        admin = make_actor(role="admin")
        self.assertTrue(ExamService._is_lead_or_admin(admin, exam))

    async def test_admin_can_reassign_draft_lead_without_rewriting_creator(
        self,
    ) -> None:
        db = AsyncMock()
        admin = make_actor(role="admin")
        creator_id = uuid4()
        old_lead = uuid4()
        new_lead = uuid4()
        exam = make_exam(
            created_by_actor_id=creator_id,
            lead_teacher_id=old_lead,
            authoring_version=3,
        )

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=exam),
            ),
            patch.object(
                ExamService,
                "_validate_lead_teacher",
                new=AsyncMock(),
            ) as validate,
            patch.object(
                ExamRepository,
                "save_exam",
                new=AsyncMock(side_effect=lambda _db, row: row),
            ) as save,
        ):
            result = await ExamService.assign_lead_teacher(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=exam.id,
                lead_teacher_id=new_lead,
                expected_authoring_version=3,
            )

        validate.assert_awaited_once_with(
            db,
            teacher_id=new_lead,
            curriculum_subject_id=exam.curriculum_subject_id,
            term_id=exam.term_id,
        )
        save.assert_awaited_once()
        db.commit.assert_awaited_once()
        self.assertEqual(result.lead_teacher_id, new_lead)
        self.assertEqual(result.created_by_actor_id, creator_id)
        self.assertEqual(result.lead_assigned_by_actor_id, admin.id)
        self.assertEqual(result.authoring_version, 4)

    async def test_lead_cannot_be_reassigned_after_draft(self) -> None:
        db = AsyncMock()
        admin = make_actor(role="admin")
        exam = make_exam(status=ExamStatus.SUBMITTED)

        with (
            patch.object(
                ExamRepository,
                "get_exam_by_id",
                new=AsyncMock(return_value=exam),
            ),
            self.assertRaisesRegex(ExamStateError, "DRAFT"),
        ):
            await ExamService.assign_lead_teacher(
                db,
                actor=admin,  # type: ignore[arg-type]
                exam_id=exam.id,
                lead_teacher_id=uuid4(),
                expected_authoring_version=exam.authoring_version,
            )


if __name__ == "__main__":
    unittest.main()
