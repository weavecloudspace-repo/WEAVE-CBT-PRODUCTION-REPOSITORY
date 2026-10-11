"""The discovery path must remain testable without PySide6, UAC or Docker."""
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_public_linux_state_requires_root_owned_nonwritable_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "weave-cbt-manager.json"
            marker.write_text(json.dumps({
                "schema_version": 1, "installed_version": "1.0",
                "install_directory": str(Path(directory) / "install"),
                "data_directory": str(Path(directory) / "data"),
            }))
            with patch.object(bridge, "PUBLIC_LINUX_STATE", marker):
                with patch.object(Path, "lstat", return_value=Mock(
                    st_uid=0, st_mode=stat.S_IFREG | 0o644
                )):
                    self.assertEqual(bridge._public_linux_installation()["installed_version"], "1.0")
                with patch.object(Path, "lstat", return_value=Mock(
                    st_uid=1001, st_mode=stat.S_IFREG | 0o644
                )):
                    self.assertIsNone(bridge._public_linux_installation())
                with patch.object(Path, "lstat", return_value=Mock(
                    st_uid=0, st_mode=stat.S_IFREG | 0o666
                )):
                    self.assertIsNone(bridge._public_linux_installation())
                with patch.object(Path, "lstat", return_value=Mock(
                    st_uid=0, st_mode=stat.S_IFLNK | 0o644
                )):
                    self.assertIsNone(bridge._public_linux_installation())

    def test_unreadable_private_linux_state_uses_trusted_public_projection(self):
        safe_metadata = {
            "schema_version": 1, "installed_version": "1.0",
            "install_directory": "/opt/weave-cbt",
            "data_directory": "/var/lib/weave-cbt",
        }
        with patch.object(bridge, "candidates", return_value=[]), \
             patch.object(bridge, "state_path", return_value=Path("/root-private/install.json")), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "stat", side_effect=PermissionError), \
             patch.object(bridge, "_public_linux_installation", return_value=safe_metadata):
            found = bridge.discover(windows=False)
        self.assertTrue(found.server_installed)
        self.assertFalse(found.manager_installed)
        self.assertEqual(found.installation["installed_version"], "1.0")

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
