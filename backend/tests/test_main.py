from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DEBUG"] = "false"

from app.main import app


class MainTests(unittest.TestCase):
    def test_core_local_routes_are_registered(self) -> None:
        openapi_paths = app.openapi()["paths"]
        paths = set(openapi_paths)

        self.assertIn("/api/v1/installation/status", paths)
        self.assertIn("/api/v1/installation/pair", paths)
        self.assertIn("/api/v1/auth/login", paths)
        self.assertIn("/api/v1/sync/status", paths)
        self.assertIn("/api/v1/sync/reconcile", paths)
        self.assertIn("/api/v1/media/question-images", paths)
        self.assertIn("/api/v1/questions/banks", paths)
        self.assertIn("/api/v1/questions/banks/{curriculum_subject_id}", paths)
        self.assertIn("/api/v1/questions/banks/authorable", paths)
        self.assertIn("/api/v1/questions/banks/{bank_id}/single-choice", paths)
        self.assertIn("/api/v1/questions/banks/{bank_id}/multiple-choice", paths)
        self.assertIn("/api/v1/questions/{question_id}/image", paths)

        self.assertIn("/api/v1/exams", paths)
        self.assertIn("/api/v1/exams/{exam_id}", paths)
        self.assertIn("get", openapi_paths["/api/v1/exams/{exam_id}"])
        self.assertIn("/api/v1/exams/{exam_id}/questions/configuration", paths)
        self.assertIn("/api/v1/exams/{exam_id}/submit", paths)
        self.assertIn("/api/v1/exams/{exam_id}/return-to-draft", paths)
        self.assertIn("/api/v1/exams/{exam_id}/seal", paths)
        self.assertIn("/api/v1/exams/{exam_id}/revisions", paths)
        self.assertIn("/api/v1/exams/{exam_id}/activate", paths)
        self.assertIn("/api/v1/exams/{exam_id}/suspend", paths)
        self.assertIn("/api/v1/exams/{exam_id}/resume", paths)
        self.assertIn("/api/v1/exams/{exam_id}/close", paths)
        self.assertIn("/api/v1/exams/{exam_id}/cancel", paths)
        self.assertIn("/api/v1/exams/invigilators/available", paths)
        self.assertIn("/api/v1/exams/{exam_id}/invigilators", paths)
        self.assertIn("/api/v1/exams/{exam_id}/invigilators/remove", paths)
        self.assertIn("/api/v1/exams/{exam_id}/manual-questions", paths)
        self.assertIn("/api/v1/exams/{exam_id}/manual-questions/remove", paths)
        self.assertIn("/api/v1/exams/{exam_id}/manual-questions/reorder", paths)

        self.assertIn("/api/v1/exams/{exam_id}/candidates", paths)
        self.assertIn("/api/v1/candidates/{candidate_id}", paths)
        self.assertIn("/api/v1/candidates/{candidate_id}/block", paths)
        self.assertIn("/api/v1/candidates/{candidate_id}/unblock", paths)
        self.assertIn(
            "/api/v1/candidates/{candidate_id}/late-start-authorizations",
            paths,
        )
        self.assertIn(
            "/api/v1/late-start-authorizations/{authorization_id}/revoke",
            paths,
        )

        self.assertIn(
            "/api/v1/academics/session/current",
            paths,
        )

        self.assertIn(
            "/api/v1/academics/term/current",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
