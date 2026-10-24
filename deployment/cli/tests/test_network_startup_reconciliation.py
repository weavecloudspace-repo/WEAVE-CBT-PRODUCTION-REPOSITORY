"""Windows startup reconciliation must be bounded and opt-in (no host mutations)."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weave_cli.commands import network
from weave_cli.commands.lan import LanError
from weave_cli.platforms.wsl_session import task_script


class StartupNetworkReconciliationTests(unittest.TestCase):
    def stack(self, data, *, runtime_type="wsl2", admin=True):
        return SimpleNamespace(
            installation=SimpleNamespace(data_directory=data, runtime_type=runtime_type),
            platform=SimpleNamespace(is_admin=lambda: admin),
        )

    def test_new_install_skips_all_network_operations(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("weave_cli.commands.lan.configure") as configure:
                self.assertFalse(network._startup_reconcile(self.stack(Path(folder))))
                configure.assert_not_called()

    def test_native_linux_never_uses_windows_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(network._startup_reconcile(self.stack(Path(folder), runtime_type="native")))

    def test_orphaned_tls_is_not_treated_as_new_install(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "tls-lan.json").write_text("{}")
            with self.assertRaisesRegex(LanError, "without base LAN"):
                network._startup_reconcile(self.stack(Path(folder)))

    def test_configured_install_retries_transient_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / "lan.json").write_text("{}")
            saved = {"listen_address": "10.10.0.1", "client_subnet": "10.10.0.0/24",
                     "wsl_address": "172.25.0.2"}
            with (
                patch("weave_cli.commands.lan.configure", side_effect=[LanError("WSL starting"), True]) as configure,
                patch("weave_cli.commands.lan._read_state", return_value=saved),
                patch.object(network, "_expected_ports", return_value=(80,)),
                patch.object(network, "_windows_refresh_health") as health,
                patch.object(network.time, "sleep") as sleep,
            ):
                self.assertTrue(network._startup_reconcile(self.stack(data), attempts=3, delay=0.01))
            self.assertEqual(configure.call_count, 2)
            sleep.assert_called_once_with(0.01)
            health.assert_called_once_with(saved, (80,), repair=False)

    def test_permanent_failure_is_bounded_and_never_restarts_helper(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / "lan.json").write_text("{}")
            with (
                patch("weave_cli.commands.lan.configure", side_effect=LanError("invalid saved interface")) as configure,
                patch.object(network.time, "sleep") as sleep,
                patch.object(network, "_restart_ip_helper") as restart,
            ):
                with self.assertRaisesRegex(LanError, "after 3 attempts"):
                    network._startup_reconcile(self.stack(data), attempts=3, delay=0)
            self.assertEqual(configure.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            restart.assert_not_called()

    def test_configured_install_requires_elevation(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / "lan.json").write_text("{}")
            with self.assertRaisesRegex(LanError, "Administrator"):
                network._startup_reconcile(self.stack(data, admin=False))

    def test_keeper_runs_startup_command_not_legacy_refresh(self):
        with patch("weave_cli.platforms.wsl_session._encoded", side_effect=lambda script: script):
            script = task_script("WeaveCBT")
        self.assertIn("network startup-reconcile", script)
        self.assertNotIn("network refresh | Out-Null", script)
        self.assertIn("Get-Content -LiteralPath $helperPath -Raw", script)


if __name__ == "__main__":
    unittest.main()
