import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from weave_cli.installation import (
    INSTALLATION_SCHEMA_VERSION,
    InstallationManager,
    InstallationState,
    InstallationStateError,
)
from weave_cli.platforms.base import BasePlatform


class TestPlatform(BasePlatform):
    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path

    @property
    def default_install_directory(self) -> Path:
        return self._state_path.parent / "install"

    @property
    def default_data_directory(self) -> Path:
        return self._state_path.parent / "data"

    @property
    def installation_state_path(self) -> Path:
        return self._state_path

    def is_admin(self) -> bool:
        return True

    def start_docker_engine(self, runtime_target: str | None = None) -> None:
        return None


class InstallationManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.install_directory = root / "install"
        self.data_directory = root / "data"
        self.install_directory.mkdir()
        self.data_directory.mkdir()
        (self.install_directory / "compose.yaml").touch()
        (self.data_directory / "runtime.env").touch()

        self.state_path = root / "state" / "install.json"
        self.manager = InstallationManager(TestPlatform(self.state_path))
        self.state = InstallationState(
            install_directory=self.install_directory,
            data_directory=self.data_directory,
            installed_version="1.0.0",
            runtime_type="native",
            installed_at=datetime.now(timezone.utc).isoformat(),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_then_load_round_trip(self):
        self.manager.create(self.state)

        self.assertTrue(self.manager.exists())
        self.assertEqual(self.manager.load(), self.state)

    def test_create_refuses_to_overwrite_existing_state(self):
        self.manager.create(self.state)

        with self.assertRaisesRegex(InstallationStateError, "already exists"):
            self.manager.create(self.state)

    def test_load_rejects_invalid_json(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text("{invalid", encoding="utf-8")

        with self.assertRaisesRegex(InstallationStateError, "invalid JSON"):
            self.manager.load()

    def test_load_rejects_unsupported_schema_version(self):
        self.manager.create(self.state)

        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload["schema_version"] = INSTALLATION_SCHEMA_VERSION + 1
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(InstallationStateError, "Unsupported"):
            self.manager.load()

    def test_validate_requires_compose_file(self):
        (self.install_directory / "compose.yaml").unlink()

        with self.assertRaisesRegex(InstallationStateError, "Compose file"):
            self.manager.validate(self.state)

    def test_validate_requires_runtime_env(self):
        (self.data_directory / "runtime.env").unlink()

        with self.assertRaisesRegex(
            InstallationStateError,
            "Runtime environment file",
        ):
            self.manager.validate(self.state)

    def test_update_replaces_existing_metadata(self):
        self.manager.create(self.state)

        updated = InstallationState(
            install_directory=self.install_directory,
            data_directory=self.data_directory,
            installed_version="1.1.0",
            runtime_type="native",
            installed_at=self.state.installed_at,
        )

        self.manager.update(updated)

        self.assertEqual(self.manager.load().installed_version, "1.1.0")

    def test_update_requires_existing_state(self):
        with self.assertRaisesRegex(InstallationStateError, "no installation"):
            self.manager.update(self.state)

    def test_delete_removes_state_only(self):
        self.manager.create(self.state)

        self.manager.delete()

        self.assertFalse(self.manager.exists())
        self.assertTrue(self.install_directory.is_dir())
        self.assertTrue(self.data_directory.is_dir())


if __name__ == "__main__":
    unittest.main()
