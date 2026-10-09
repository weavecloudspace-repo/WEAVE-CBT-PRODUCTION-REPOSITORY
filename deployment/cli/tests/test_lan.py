"""WSL school-LAN forwarding contract: pure mocked tests, no host mutations."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner
from weave_cli.commands import lan
from weave_cli.main import app


class LanTests(unittest.TestCase):
    def test_cli_command_registered(self):
        result = CliRunner().invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("lan", result.output)

    def test_rejects_public_and_wildcard_listeners(self):
        for address in ("0.0.0.0", "127.0.0.1", "8.8.8.8", "169.254.3.4"):
            with self.subTest(address=address), self.assertRaises(lan.LanError):
                lan._private_address(address)

    def test_restricts_to_school_private_subnet(self):
        for subnet in ("0.0.0.0/0", "10.0.0.0/8", "192.168.0.0/16",
                       "192.168.2.0/24", "8.8.8.0/24"):
            with self.subTest(subnet=subnet), self.assertRaises(lan.LanError):
                lan._private_subnet(subnet, "192.168.1.24")
        self.assertEqual(
            lan._private_subnet("192.168.1.0/24", "192.168.1.24"),
            "192.168.1.0/24",
        )

    def test_refresh_without_configuration_is_harmless(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(lan, "_powershell") as ps:
                self.assertFalse(lan.configure(Path(directory), refresh=True))
                ps.assert_not_called()

    def test_never_overwrites_unowned_portproxy(self):
        with tempfile.TemporaryDirectory() as directory, (
            patch.object(lan, "_assert_private_interface"),
            patch.object(lan, "_mapped_destination", return_value="172.22.1.99/80"),
            patch.object(lan, "_firewall_exists", return_value=False),
            patch.object(lan, "_run") as netsh,
        ):
            with self.assertRaisesRegex(lan.LanError, "unrelated"):
                lan.configure(Path(directory), listen_address="192.168.1.24",
                              client_subnet="192.168.1.0/24")
            netsh.assert_not_called()

    def test_new_forwarding_is_bound_to_selected_host_and_subnet(self):
        with tempfile.TemporaryDirectory() as directory, (
            patch.object(lan, "_assert_private_interface"),
            patch.object(lan, "_mapped_destination", return_value=None),
            patch.object(lan, "_firewall_exists", return_value=False),
            patch.object(lan, "_wsl_address", return_value="172.28.1.4"),
            patch.object(lan, "_add_firewall") as firewall,
            patch.object(lan, "_verify_firewall") as verify,
            patch.object(lan, "_run") as commands,
        ):
            data = Path(directory)
            self.assertTrue(lan.configure(data, listen_address="192.168.1.24",
                                          client_subnet="192.168.1.0/24"))
            commands.assert_called_once_with(
                ["netsh.exe", "interface", "portproxy", "add", "v4tov4",
                 "listenport=80", "listenaddress=192.168.1.24", "connectport=80",
                 "connectaddress=172.28.1.4"],
            )
            firewall.assert_called_once_with("192.168.1.24", "192.168.1.0/24")
            verify.assert_called_once()
            self.assertEqual(json.loads((data / "lan.json").read_text())["wsl_address"],
                             "172.28.1.4")

    def test_refresh_reconciles_changed_wsl_nat_address(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "lan.json").write_text(json.dumps({
                "listen_address": "192.168.1.24",
                "client_subnet": "192.168.1.0/24",
                "wsl_address": "172.28.1.4",
            }))
            with (
                patch.object(lan, "_assert_private_interface"),
                patch.object(lan, "_mapped_destination", return_value="172.28.1.4/80"),
                patch.object(lan, "_firewall_exists", return_value=True),
                patch.object(lan, "_wsl_address", return_value="172.29.1.7"),
                patch.object(lan, "_verify_firewall"),
                patch.object(lan, "_run") as commands,
            ):
                self.assertTrue(lan.configure(data, refresh=True))
                self.assertEqual(commands.call_count, 2)
                self.assertIn("delete", commands.call_args_list[0].args[0])
                self.assertIn("connectaddress=172.29.1.7", commands.call_args_list[1].args[0])
                self.assertEqual(json.loads((data / "lan.json").read_text())["wsl_address"],
                                 "172.29.1.7")

    def test_refresh_rejects_mapping_changed_outside_weave(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "lan.json").write_text(json.dumps({
                "listen_address": "192.168.1.24",
                "client_subnet": "192.168.1.0/24",
                "wsl_address": "172.28.1.4",
            }))
            with (
                patch.object(lan, "_assert_private_interface"),
                patch.object(lan, "_mapped_destination", return_value="172.28.9.9/80"),
                patch.object(lan, "_run") as commands,
            ):
                with self.assertRaisesRegex(lan.LanError, "unrelated"):
                    lan.configure(data, refresh=True)
                commands.assert_not_called()

    def test_linux_runtime_never_runs_windows_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(lan, "configure") as configure:
                lan.refresh_if_configured(Path(directory), runtime_type="native")
                configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
