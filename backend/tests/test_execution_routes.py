import os
import unittest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.attempts.router import operator_router, student_router
from app.domains.auth.student_router import router as student_auth_router
from app.domains.candidates.makeup_router import router as makeup_router
from app.domains.exams.timetable_router import router as timetable_router
from app.domains.results.router import router as results_router


class ExecutionRouteTests(unittest.TestCase):
    def test_student_auth_routes_exist(self):
        paths = {route.path for route in student_auth_router.routes}
        self.assertIn("/student/auth/login", paths)
        self.assertIn("/student/auth/status", paths)
        self.assertIn("/student/auth/logout", paths)

    def test_student_attempt_routes_exist(self):
        paths = {route.path for route in student_router.routes}
        self.assertIn("/student/attempts/current/start", paths)
        self.assertIn("/student/attempts/current", paths)
        self.assertIn("/student/attempts/current/submit", paths)

    def test_operator_attempt_routes_exist(self):
        paths = {route.path for route in operator_router.routes}
        self.assertIn("/attempts/{attempt_id}/interrupt", paths)
        self.assertIn("/attempts/{attempt_id}/resume", paths)
        self.assertIn("/attempts/{attempt_id}/terminate", paths)

    def test_makeup_and_result_routes_exist(self):
        makeup_paths = {route.path for route in makeup_router.routes}
        result_paths = {route.path for route in results_router.routes}
        self.assertIn("/exams/{exam_id}/missed-candidates", makeup_paths)
        self.assertIn("/candidates/{candidate_id}/makeup-authorizations", makeup_paths)
        self.assertIn("/exams/{exam_id}/results", result_paths)

    def test_batch_exam_start_route_exists(self):
        paths = {route.path for route in timetable_router.routes}
        self.assertIn("/exams/start-batch", paths)
        self.assertIn("/exams/{exam_id}/timetable-impact", paths)


if __name__ == "__main__":
    unittest.main()
