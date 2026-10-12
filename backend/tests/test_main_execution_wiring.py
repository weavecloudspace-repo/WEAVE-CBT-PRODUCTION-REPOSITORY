import os
import unittest
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


class MainWiringTests(unittest.TestCase):
    def test_execution_routers_are_wired_into_main(self):
        source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(
            encoding="utf-8"
        )
        for name in (
            "student_auth_router",
            "student_attempts_router",
            "attempts_router",
            "makeup_router",
            "timetable_router",
            "results_router",
        ):
            self.assertIn(name, source)


if __name__ == "__main__":
    unittest.main()
