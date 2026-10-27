import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

TEST_ENVIRONMENT = {
    "DATABASE_URL": "postgresql+asyncpg://user:password@localhost/cbt",
    "DEBUG": "false",
    "REDIS_URL": "redis://localhost:6379/0",
    "WEAVE_API_BASE_URL": "https://weave.invalid",
}

with patch.dict(os.environ, TEST_ENVIRONMENT):
    from app.core.settings import Settings


class DatabaseSettingsTests(unittest.TestCase):
    def setUp(self):
        environment_patcher = patch.dict(os.environ, {}, clear=True)
        environment_patcher.start()
        self.addCleanup(environment_patcher.stop)

        self.required_settings = {
            "REDIS_URL": "redis://localhost:6379/0",
            "WEAVE_API_BASE_URL": "https://weave.invalid",
        }

    def test_database_url_is_required(self):
        with self.assertRaises(ValidationError) as context:
            Settings(_env_file=None, **self.required_settings)

        self.assertIn("DATABASE_URL", str(context.exception))

    def test_database_url_cannot_be_blank(self):
        with self.assertRaisesRegex(
            ValidationError,
            "DATABASE_URL must use PostgreSQL",
        ):
            Settings(
                _env_file=None,
                DATABASE_URL="   ",
                **self.required_settings,
            )

    def test_database_url_rejects_non_postgresql_drivers(self):
        with self.assertRaisesRegex(
            ValidationError,
            "DATABASE_URL must use PostgreSQL",
        ):
            Settings(
                _env_file=None,
                DATABASE_URL="sqlite+aiosqlite:///cbt.db",
                **self.required_settings,
            )

    def test_database_url_normalizes_postgresql_scheme(self):
        settings = Settings(
            _env_file=None,
            DATABASE_URL="postgresql://user:password@localhost/cbt",
            **self.required_settings,
        )

        self.assertEqual(
            settings.DATABASE_URL,
            "postgresql+asyncpg://user:password@localhost/cbt",
        )

    def test_production_database_pool_defaults(self):
        settings = Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://user:password@localhost/cbt",
            **self.required_settings,
        )

        self.assertEqual(settings.DATABASE_POOL_SIZE, 10)
        self.assertEqual(settings.DATABASE_MAX_OVERFLOW, 5)
        self.assertEqual(settings.DATABASE_POOL_TIMEOUT_SECONDS, 20)
        self.assertEqual(settings.DATABASE_POOL_RECYCLE_SECONDS, 1800)

    def test_database_pool_settings_accept_runtime_overrides(self):
        settings = Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://user:password@localhost/cbt",
            DATABASE_POOL_SIZE=8,
            DATABASE_MAX_OVERFLOW=3,
            DATABASE_POOL_TIMEOUT_SECONDS=25,
            DATABASE_POOL_RECYCLE_SECONDS=600,
            **self.required_settings,
        )

        self.assertEqual(settings.DATABASE_POOL_SIZE, 8)
        self.assertEqual(settings.DATABASE_MAX_OVERFLOW, 3)
        self.assertEqual(settings.DATABASE_POOL_TIMEOUT_SECONDS, 25)
        self.assertEqual(settings.DATABASE_POOL_RECYCLE_SECONDS, 600)

    def test_compose_passes_pool_defaults_and_overrides_to_database_services(self):
        import yaml

        compose_file = Path(__file__).resolve().parents[2] / "deployment" / "compose.yaml"
        compose = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        defaults = {
            "DATABASE_POOL_SIZE": 10,
            "DATABASE_MAX_OVERFLOW": 5,
            "DATABASE_POOL_TIMEOUT_SECONDS": 20,
            "DATABASE_POOL_RECYCLE_SECONDS": 1800,
        }

        for service in ("bootstrap", "api", "worker"):
            with self.subTest(service=service):
                environment = compose["services"][service]["environment"]
                for key, default in defaults.items():
                    self.assertEqual(environment[key], f"${{{key}:-{default}}}")

    def test_identity_storage_path_can_be_overridden_from_environment(self):
        settings = Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://user:password@localhost/cbt",
            IDENTITY_STORAGE_PATH="./.weave-cbt/identity",
            **self.required_settings,
        )

        self.assertEqual(
            settings.IDENTITY_STORAGE_PATH,
            Path(".weave-cbt/identity"),
        )


if __name__ == "__main__":
    unittest.main()
