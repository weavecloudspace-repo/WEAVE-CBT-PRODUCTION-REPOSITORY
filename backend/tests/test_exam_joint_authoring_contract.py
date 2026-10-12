from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DEBUG"] = "false"

from app.domains.exams.models import (
    Exam,
    ExamQuestion,
    ExamQuestionSelection,
)
from app.domains.exams.router import router
from app.domains.exams.schemas import (
    ExamAuthoringAction,
    ExamQuestionSelectionResponse,
    ExamResponse,
)


class JointAuthoringContractTests(unittest.TestCase):
    def test_shared_exam_identity_does_not_include_title(self) -> None:
        index = next(
            item
            for item in Exam.__table__.indexes
            if item.name == "uq_exams_scope_revision"
        )
        self.assertTrue(index.unique)
        self.assertEqual(
            [column.name for column in index.columns],
            [
                "term_id",
                "curriculum_subject_id",
                "assessment_component_id",
                "revision_number",
            ],
        )

    def test_exam_has_positive_authoring_version_column(self) -> None:
        column = Exam.__table__.c.authoring_version
        self.assertFalse(column.nullable)
        self.assertIsNotNone(column.server_default)
        self.assertIn("authoring_version", ExamResponse.model_fields)
        self.assertEqual(ExamAuthoringAction().expected_authoring_version, 1)

    def test_manual_selection_requires_contributor_and_frozen_question_preserves_it(
        self,
    ) -> None:
        selection_column = ExamQuestionSelection.__table__.c.added_by_actor_id
        frozen_column = ExamQuestion.__table__.c.added_by_actor_id
        self.assertFalse(selection_column.nullable)
        self.assertTrue(frozen_column.nullable)
        self.assertIn("added_by_actor_id", ExamQuestionSelectionResponse.model_fields)

    def test_router_exposes_manual_contribution_list(self) -> None:
        route = next(
            route
            for route in router.routes
            if getattr(route, "path", None) == "/exams/{exam_id}/manual-questions"
            and "GET" in getattr(route, "methods", set())
        )
        self.assertIsNotNone(route)


if __name__ == "__main__":
    unittest.main()
