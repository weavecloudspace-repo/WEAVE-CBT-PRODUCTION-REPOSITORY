"""The discovery path must remain testable without PySide6, UAC or Docker."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class DiscoveryTests(unittest.TestCase):
    def test_absent_manager_is_not_server(self):
        with patch.object(bridge, "candidates", return_value=[]), \
             patch.object(bridge, "state_path", return_value=Path("/nonexistent/weave-cbt/install.json")):
            self.assertFalse(bridge.discover().manager_installed)
            self.assertFalse(bridge.discover().server_installed)

    def test_existing_manager_is_not_equivalent_to_installed_server(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "weave"
            cli.touch()
            with patch.object(bridge, "candidates", return_value=[cli]), \
                 patch.object(bridge, "state_path", return_value=Path(directory) / "install.json"), \
                 patch.object(bridge.subprocess, "run") as run:
                run.return_value.returncode = 0
                detected = bridge.discover()
                self.assertTrue(detected.manager_installed)
                self.assertFalse(detected.server_installed)

    def test_state_requires_real_compose_and_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root / "install"
            data = root / "data"
            install.mkdir()
            data.mkdir()
            (install / "compose.yaml").write_text("services: {}")
            (data / "runtime.env").write_text("SECRET=value")
            state = {"schema_version": 1, "installed_version": "1.0", "install_directory": str(install), "data_directory": str(data)}
            state_file = root / "install.json"
            state_file.write_text(json.dumps(state))
            with patch.object(bridge, "candidates", return_value=[]), \
                 patch.object(bridge, "state_path", return_value=state_file):
                self.assertTrue(bridge.discover().server_installed)
                (install / "compose.yaml").unlink()
                self.assertFalse(bridge.discover().server_installed)
