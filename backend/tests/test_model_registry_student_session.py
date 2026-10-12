import os
import unittest
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


class ModelRegistryTests(unittest.TestCase):
    def test_student_session_model_is_registered_for_bootstrap(self):
        registry = (
            Path(__file__).resolve().parents[1] / "app" / "model_registry.py"
        ).read_text(encoding="utf-8")
        self.assertIn("student_models", registry)


if __name__ == "__main__":
    unittest.main()
