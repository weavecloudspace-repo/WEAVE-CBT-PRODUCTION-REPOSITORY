"""Command handlers are tested without running Docker or touching host installations."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import typer
from typer.testing import CliRunner
from weave_cli.installation import InstallationState
from weave_cli.commands import doctor, logs, restart, start, status, stop, uninstall, update


def stack_fixture(data_dir: Path | None = None):
    stack = MagicMock()
    stack.runtime.docker_engine_running.return_value = True
    stack.runtime.docker_cli_available.return_value = True
    stack.runtime.docker_compose_available.return_value = True
    stack.platform.is_admin.return_value = True
    stack.compose.status.return_value.stdout = "api-1  api  Up"
    stack.compose.logs.return_value.stdout = "test log"
    stack.compose.logs.return_value.stderr = ""
    stack.installation = InstallationState(
        install_directory=data_dir or Path("/fake/install"),
        data_directory=data_dir or Path("/fake/data"),
        installed_version="v1",
        runtime_type="native",
        installed_at=datetime.now(timezone.utc).isoformat(),
    )
    return stack


class CommandTests(unittest.TestCase):
    runner = CliRunner()

    def invoke(self, module, args=(), input=None):
        app = typer.Typer()
        module.register(app)
        return self.runner.invoke(app, list(args), input=input)

    def test_all_commands_register(self):
        app = typer.Typer()
        for module in (start, stop, restart, status, logs, doctor, update, uninstall):
            module.register(app)
        result = self.runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        for name in ("start", "stop", "restart", "status", "logs", "doctor", "update", "uninstall"):
            self.assertIn(name, result.output)

    def test_start_recovers_stopped_engine(self):
        stack = stack_fixture()
        stack.runtime.docker_engine_running.side_effect = [False, True]
        with patch.object(start, "get_stack", return_value=stack):
            result = self.invoke(start)
        self.assertEqual(result.exit_code, 0, result.output)
        stack.platform.start_docker_engine.assert_called_once()
        stack.compose.start.assert_called_once()

    def test_stop_preserves_volumes(self):
        stack = stack_fixture()
        with patch.object(stop, "get_stack", return_value=stack):
            result = self.invoke(stop)
        self.assertEqual(result.exit_code, 0, result.output)
        stack.compose.stop.assert_called_once()
        stack.compose.destroy.assert_not_called()

    def test_restart_uses_restart(self):
        stack = stack_fixture()
        with patch.object(restart, "get_stack", return_value=stack):
            result = self.invoke(restart)
        self.assertEqual(result.exit_code, 0, result.output)
        stack.compose.restart.assert_called_once()

    def test_unknown_logs_service_is_rejected(self):
        with patch.object(logs, "get_stack") as dependency:
            result = self.invoke(logs, ["invalid"])
        self.assertEqual(result.exit_code, 2, result.output)
        dependency.assert_not_called()

    def test_logs_are_sent_to_compose(self):
        stack = stack_fixture()
        with patch.object(logs, "get_stack", return_value=stack):
            result = self.invoke(logs, ["api"])
        self.assertEqual(result.exit_code, 0, result.output)
        stack.compose.logs.assert_called_once_with(service="api", follow=False)

    def test_status_is_read_only(self):
        stack = stack_fixture()
        with patch.object(status, "get_stack", return_value=stack):
            result = self.invoke(status)
        self.assertEqual(result.exit_code, 0, result.output)
        stack.compose.status.assert_called_once()
        stack.compose.start.assert_not_called()

    def test_doctor_is_read_only(self):
        stack = stack_fixture()
        with patch.object(doctor, "get_stack", return_value=stack):
            result = self.invoke(doctor)
        self.assertEqual(result.exit_code, 0, result.output)
        stack.compose.config.assert_called_once()
        stack.compose.start.assert_not_called()

    def test_uninstall_without_purge_preserves_volumes(self):
        stack = stack_fixture()
        with patch.object(uninstall, "get_stack", return_value=stack):
            result = self.invoke(uninstall, ["--yes"])
        self.assertEqual(result.exit_code, 0, result.output)
        stack.compose.stop.assert_called_once()
        stack.compose.destroy.assert_not_called()
        stack.manager.delete.assert_called_once()

    def test_purge_requires_specific_confirmation_phrase(self):
        stack = stack_fixture()
        with patch.object(uninstall, "get_stack", return_value=stack):
            result = self.invoke(uninstall, ["--yes", "--purge-volumes"], input="NO\n")
        self.assertEqual(result.exit_code, 0, result.output)
        stack.compose.destroy.assert_not_called()
        stack.manager.delete.assert_not_called()

    def test_update_rejects_latest(self):
        with patch.object(update, "get_stack") as loader:
            result = self.invoke(update, ["--image", "weave:latest"])
        self.assertEqual(result.exit_code, 1, result.output)
        loader.assert_not_called()

    def test_update_pull_failure_restores_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "runtime.env"
            original = b"WEAVE_IMAGE=ghcr.io/weave/cbt:v1\nOTHER=preserved\n"
            env.write_bytes(original)
            stack = stack_fixture(Path(directory))
            stack.compose.pull_weave_image.side_effect = RuntimeError("pull failed")
            with (
                patch.object(update, "get_stack", return_value=stack),
                patch.object(update, "save_runtime_env", side_effect=lambda path, data: path.write_bytes(data)),
            ):
                result = self.invoke(update, ["--image", "ghcr.io/weave/cbt:v2"], input="y\n")
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertEqual(env.read_bytes(), original)
            stack.manager.update.assert_not_called()
            stack.compose.start.assert_called_once()

    def test_update_commits_metadata_after_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "runtime.env"
            env.write_bytes(b"WEAVE_IMAGE=ghcr.io/weave/cbt:v1\n")
            stack = stack_fixture(Path(directory))
            with (
                patch.object(update, "get_stack", return_value=stack),
                patch.object(update, "save_runtime_env", side_effect=lambda path, data: path.write_bytes(data)),
                patch.object(update, "_verify_started_stack") as verify,
            ):
                result = self.invoke(update, ["--image", "ghcr.io/weave/cbt:v2"], input="y\n")
            self.assertEqual(result.exit_code, 0, result.output)
            verify.assert_called_once()
            stack.manager.update.assert_called_once()
            self.assertIn(b"ghcr.io/weave/cbt:v2", env.read_bytes())


if __name__ == "__main__":
    unittest.main()
