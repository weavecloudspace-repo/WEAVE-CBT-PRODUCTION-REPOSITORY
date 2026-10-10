"""Image/database rollback tests, no Docker or installed school required."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import typer
from typer.testing import CliRunner

from weave_cli.commands import rollback, update
from weave_cli.commands.update_recovery import (
    UpdateRecovery,
    guard_pending_update,
    read_recovery,
    recovery_path,
    save_recovery,
)
from weave_cli.installation import InstallationState


def _stack(directory: Path):
    stack = MagicMock()
    stack.platform.is_admin.return_value = True
    stack.runtime.docker_engine_running.return_value = True
    stack.installation = InstallationState(
        install_directory=directory,
        data_directory=directory,
        installed_version="old-version",
        runtime_type="native",
        installed_at=datetime.now(timezone.utc).isoformat(),
    )
    return stack


def _invoke(module, arguments=(), answer="y\n"):
    cli = typer.Typer()
    module.register(cli)
    return CliRunner().invoke(cli, list(arguments), input=answer)


class DatabaseRollbackTests(unittest.TestCase):
    def _setup(self, directory):
        path = Path(directory)
        env_file = path / "runtime.env"
        env_file.write_bytes(b"WEAVE_IMAGE=ghcr.io/example/cbt:v1\nOTHER=kept\n")
        return _stack(path), env_file

    def test_successful_update_retains_snapshot_for_manual_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, env_file = self._setup(directory)
            with (
                patch.object(update, "get_stack", return_value=stack),
                patch.object(update, "_verify_started_stack"),
            ):
                result = _invoke(update, ["--image", "ghcr.io/example/cbt:v2"])
            self.assertEqual(result.exit_code, 0, result.output)
            record = read_recovery(recovery_path(Path(directory)))
            self.assertEqual(record.phase, "ready")
            self.assertEqual(record.previous_image, "ghcr.io/example/cbt:v1")
            self.assertEqual(record.target_image, "ghcr.io/example/cbt:v2")
            stack.compose.verify_database_maintenance.assert_called_once()
            stack.compose.stop_application.assert_called_once()
            stack.compose.snapshot_database.assert_called_once_with(
                record.snapshot_database
            )
            stack.compose.restore_database.assert_not_called()
            stack.compose.start.assert_called_once()
            self.assertIn(b"cbt:v2", env_file.read_bytes())
            stack.manager.update.assert_called_once()

    def test_failed_new_image_restores_prior_database_and_image(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, env_file = self._setup(directory)
            stack.compose.start.side_effect = [RuntimeError("new API failed"), None]
            with (
                patch.object(update, "get_stack", return_value=stack),
                patch.object(update, "_verify_started_stack"),
            ):
                result = _invoke(update, ["--image", "ghcr.io/example/cbt:v2"])
            self.assertEqual(result.exit_code, 1, result.output)
            stack.compose.restore_database.assert_called_once()
            self.assertEqual(stack.compose.start.call_count, 2)
            self.assertEqual(stack.compose.stop_application.call_count, 2)
            self.assertIn(b"cbt:v1", env_file.read_bytes())
            self.assertIn(b"OTHER=kept", env_file.read_bytes())
            self.assertFalse(recovery_path(Path(directory)).exists())
            self.assertEqual(
                stack.manager.update.call_args.args[0].installed_version,
                "old-version",
            )

    def test_snapshot_failure_never_attempts_database_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, env_file = self._setup(directory)
            stack.compose.snapshot_database.side_effect = RuntimeError("no disk")
            with (
                patch.object(update, "get_stack", return_value=stack),
                patch.object(update, "_verify_started_stack"),
            ):
                result = _invoke(update, ["--image", "ghcr.io/example/cbt:v2"])
            self.assertEqual(result.exit_code, 1, result.output)
            stack.compose.restore_database.assert_not_called()
            stack.compose.drop_snapshot_database.assert_not_called()
            self.assertIn(b"cbt:v1", env_file.read_bytes())
            self.assertFalse(recovery_path(Path(directory)).exists())

    def test_invalid_postgres_preflight_never_stops_server_or_rewrites_image(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, env_file = self._setup(directory)
            stack.compose.verify_database_maintenance.side_effect = RuntimeError(
                "PostgreSQL container is missing POSTGRES_DB"
            )
            with patch.object(update, "get_stack", return_value=stack):
                result = _invoke(update, ["--image", "ghcr.io/example/cbt:v2"])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("missing POSTGRES_DB", result.output)
            stack.compose.stop_application.assert_not_called()
            stack.compose.pull_weave_image.assert_not_called()
            stack.compose.snapshot_database.assert_not_called()
            stack.compose.restore_database.assert_not_called()
            self.assertIn(b"cbt:v1", env_file.read_bytes())
            self.assertFalse(recovery_path(Path(directory)).exists())

    def test_failed_database_restore_blocks_later_api_start(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, env_file = self._setup(directory)
            stack.compose.start.side_effect = RuntimeError("new migration failed")
            stack.compose.restore_database.side_effect = RuntimeError("restore blocked")
            with patch.object(update, "get_stack", return_value=stack):
                result = _invoke(update, ["--image", "ghcr.io/example/cbt:v2"])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertEqual(
                read_recovery(recovery_path(Path(directory))).phase, "pending"
            )
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                guard_pending_update(Path(directory))
            self.assertIn(b"cbt:v2", env_file.read_bytes())

    def test_manual_rollback_restores_snapshot_and_prior_image(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, env_file = self._setup(directory)
            env_file.write_bytes(b"WEAVE_IMAGE=ghcr.io/example/cbt:v2\nOTHER=kept\n")
            record = UpdateRecovery(
                previous_image="ghcr.io/example/cbt:v1",
                target_image="ghcr.io/example/cbt:v2",
                previous_version="old-version",
                snapshot_database="weave_cbt_rollback_" + "a" * 32,
                failed_database="weave_cbt_failed_" + "a" * 32,
                phase="ready",
            )
            save_recovery(recovery_path(Path(directory)), record)
            with (
                patch.object(rollback, "get_stack", return_value=stack),
                patch.object(update, "_verify_started_stack"),
            ):
                result = _invoke(rollback)
            self.assertEqual(result.exit_code, 0, result.output)
            stack.compose.restore_database.assert_called_once_with(
                record.snapshot_database, record.failed_database
            )
            self.assertIn(b"cbt:v1", env_file.read_bytes())
            self.assertFalse(recovery_path(Path(directory)).exists())

    def test_manual_rollback_declined_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, _ = self._setup(directory)
            record = UpdateRecovery(
                previous_image="v1",
                target_image="v2",
                previous_version="v1",
                snapshot_database="weave_cbt_rollback_" + "b" * 32,
                failed_database="weave_cbt_failed_" + "b" * 32,
                phase="ready",
            )
            save_recovery(recovery_path(Path(directory)), record)
            with patch.object(rollback, "get_stack", return_value=stack):
                result = _invoke(rollback, answer="n\n")
            self.assertEqual(result.exit_code, 0, result.output)
            stack.compose.restore_database.assert_not_called()
            self.assertTrue(recovery_path(Path(directory)).exists())


if __name__ == "__main__":
    unittest.main()
