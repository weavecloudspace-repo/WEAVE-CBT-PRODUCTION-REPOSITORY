"""Reinstall remains deliberately destructive-only-with-explicit-authorization."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import typer

from weave_cli.commands import reinstall


class ReinstallSafetyTests(unittest.TestCase):
    def test_rejects_implicit_purge_when_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "data"
            app = root / "app"
            data.mkdir()
            app.mkdir()
            runtime = Mock()
            manager = Mock()
            manager.exists.return_value = True
            manager.load.return_value = SimpleNamespace(
                install_directory=app, data_directory=data
            )
            platform = Mock()
            platform.is_admin.return_value = True
            platform.default_install_directory = app
            platform.default_data_directory = data
            with (
                patch.object(reinstall, "_detect_platform",
                             return_value=(platform, "native", runtime)),
                patch.object(reinstall, "InstallationManager", return_value=manager),
                patch.object(reinstall, "guard_pending_update"),
                patch.object(reinstall, "banner"),
                patch.object(reinstall, "error"),
                patch.object(reinstall, "_perform_install") as install,
            ):
                with self.assertRaises(typer.Exit):
                    reinstall.reinstall(purge_data=False, yes=True)
            install.assert_not_called()
            runtime.run_docker_command.assert_not_called()

    def test_purge_requires_typed_confirmation_even_with_yes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            platform = Mock()
            platform.is_admin.return_value = True
            platform.default_install_directory = root / "app"
            platform.default_data_directory = root / "data"
            runtime = Mock()
            manager = Mock()
            manager.exists.return_value = False
            with (
                patch.object(reinstall, "_detect_platform",
                             return_value=(platform, "native", runtime)),
                patch.object(reinstall, "InstallationManager", return_value=manager),
                patch.object(reinstall, "guard_pending_update"),
                patch.object(reinstall, "banner"),
                patch.object(reinstall, "warning"),
                patch.object(reinstall.typer, "prompt", return_value="NO"),
                patch.object(reinstall, "_perform_install") as install,
            ):
                reinstall.reinstall(purge_data=True, yes=True)
            install.assert_not_called()
            runtime.run_docker_command.assert_not_called()
