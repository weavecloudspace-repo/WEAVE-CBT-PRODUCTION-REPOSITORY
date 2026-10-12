"""Network command contracts (mocks only, never modify host networking)."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner
from weave_cli.main import app
from weave_cli.commands import network, network_dns


class NetworkManagementTests(unittest.TestCase):
    def setUp(self):
        self.stack = SimpleNamespace(
            installation=SimpleNamespace(
                runtime_type="wsl2", data_directory=Path("/nowhere/weave"),
                install_directory=Path("/nowhere/install")),
            platform=SimpleNamespace(is_admin=lambda: True),
            compose=SimpleNamespace(),
        )

    def test_https_url_uses_paired_hostname_not_http(self):
        with (patch.object(network, "get_stack", return_value=self.stack),
              patch.object(network, "_read_state", return_value={"listen_address": "192.168.1.12"}),
              patch.object(network, "_https_hostname", return_value="server.school.cbt-staging.weavecloudspace.com")):
            reply = CliRunner().invoke(app, ["network", "url", "--json"])
        self.assertEqual(reply.exit_code, 0, reply.output)
        result = json.loads(reply.output)
        self.assertEqual(result["url"], "https://server.school.cbt-staging.weavecloudspace.com/student")

    def test_legacy_http_url_without_tls(self):
        with (patch.object(network, "get_stack", return_value=self.stack),
              patch.object(network, "_read_state", return_value={"listen_address": "192.168.1.12"}),
              patch.object(network, "_https_hostname", return_value=None)):
            reply = CliRunner().invoke(app, ["network", "url", "--json"])
        self.assertEqual(reply.exit_code, 0, reply.output)
        self.assertEqual(json.loads(reply.output)["scheme"], "http")

    def test_untrusted_adapter_cannot_be_automatically_selected(self):
        adapter = {"name": "Wi-Fi", "address": "192.168.1.12", "network": "192.168.1.0/24",
                   "category": "Public", "private": True}
        self.assertIsNone(network.recommend([adapter]))
        self.assertEqual(network._candidate([adapter], "Wi-Fi")["category"], "Public")

    def test_windows_setup_command_keeps_legacy_state_path(self):
        with (patch.object(network, "get_stack", return_value=self.stack),
              patch.object(network, "configure", return_value=True) as configured):
            result = CliRunner().invoke(app, [
                "network", "setup", "--listen-address", "192.168.1.12",
                "--client-subnet", "192.168.1.0/24", "--yes",
            ])
        self.assertEqual(result.exit_code, 0, result.output)
        configured.assert_called_once_with(
            self.stack.installation.data_directory,
            listen_address="192.168.1.12", client_subnet="192.168.1.0/24",
        )

    def test_core_dns_setup_requires_https(self):
        with patch.object(network_dns.sys, "platform", "win32"):
            with self.assertRaisesRegex(network_dns.DNSError, "activate HTTPS"):
                network_dns._get_ip_and_hostname(self.stack)

    def test_linux_dns_setup_is_dispatched_to_native_systemd(self):
        self.stack.installation.runtime_type = "native"
        with patch.object(network_dns.sys, "platform", "linux"), \
             patch("weave_cli.commands.network_dns_linux.setup_linux", return_value={"configured": True}) as setup:
            result = network_dns.setup(self.stack, interface="eth0")
        self.assertTrue(result["configured"])
        setup.assert_called_once_with(self.stack, interface="eth0")


    def test_refresh_only_repairs_missing_windows_listeners_with_explicit_flag(self):
        from tempfile import TemporaryDirectory
        from weave_cli.commands import lan
        with TemporaryDirectory() as folder:
            data = Path(folder)
            self.stack.installation.data_directory = data
            saved = {"listen_address": "192.168.1.12", "client_subnet": "192.168.1.0/24",
                     "wsl_address": "172.19.225.173"}
            (data / "lan.json").write_text(json.dumps(saved))
            with (patch.object(network, "get_stack", return_value=self.stack),
                  patch.object(network, "configure", return_value=True),
                  patch.object(network, "_read_state", return_value=saved),
                  patch.object(network, "_windows_listening_ports", return_value=set()),
                  patch.object(network, "_tcp_open", return_value=True),
                  patch.object(lan, "_mapped_destination", return_value="172.19.225.173/80"),
                  patch.object(network, "_restart_ip_helper") as restart):
                result = CliRunner().invoke(app, ["network", "refresh"])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("--repair", result.output)
            restart.assert_not_called()

    def test_explicit_repair_restarts_ip_helper_only_once_and_verifies_recovery(self):
        from tempfile import TemporaryDirectory
        from weave_cli.commands import lan
        with TemporaryDirectory() as folder:
            data = Path(folder)
            self.stack.installation.data_directory = data
            saved = {"listen_address": "192.168.1.12", "client_subnet": "192.168.1.0/24",
                     "wsl_address": "172.19.225.173"}
            with (patch.object(network, "get_stack", return_value=self.stack),
                  patch.object(network, "configure", return_value=True),
                  patch.object(network, "_read_state", return_value=saved),
                  patch.object(network, "_windows_listening_ports", side_effect=[set(), {80}]),
                  patch.object(network, "_tcp_open", return_value=True),
                  patch.object(lan, "_mapped_destination", return_value="172.19.225.173/80"),
                  patch.object(network, "_restart_ip_helper") as restart):
                result = CliRunner().invoke(app, ["network", "refresh", "--repair"])
            self.assertEqual(result.exit_code, 0, result.output)
            restart.assert_called_once_with()
            self.assertIn("accepting TCP connections", result.output)

    def test_repair_does_not_restart_helper_if_wsl_backend_is_unreachable(self):
        from tempfile import TemporaryDirectory
        from weave_cli.commands import lan
        with TemporaryDirectory() as folder:
            data = Path(folder)
            self.stack.installation.data_directory = data
            saved = {"listen_address": "192.168.1.12", "client_subnet": "192.168.1.0/24",
                     "wsl_address": "172.19.225.173"}
            with (patch.object(network, "get_stack", return_value=self.stack),
                  patch.object(network, "configure", return_value=True),
                  patch.object(network, "_read_state", return_value=saved),
                  patch.object(network, "_windows_listening_ports", return_value=set()),
                  patch.object(network, "_tcp_open", side_effect=lambda address, port: address != "172.19.225.173"),
                  patch.object(lan, "_mapped_destination", return_value="172.19.225.173/80"),
                  patch.object(network, "_restart_ip_helper") as restart):
                result = CliRunner().invoke(app, ["network", "refresh", "--repair"])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("WSL backend", result.output)
            restart.assert_not_called()

    def test_doctor_reports_missing_windows_tcp_listener_and_healthy_backend(self):
        from tempfile import TemporaryDirectory
        from weave_cli.commands import lan
        with TemporaryDirectory() as folder:
            self.stack.installation.data_directory = Path(folder)
            saved = {"listen_address": "192.168.1.12", "client_subnet": "192.168.1.0/24",
                     "wsl_address": "172.19.225.173"}
            with (patch.object(network, "get_stack", return_value=self.stack),
                  patch.object(network, "inventory", return_value=[{
                      "name": "Wi-Fi", "address": "192.168.1.12", "network": "192.168.1.0/24",
                      "category": "Private", "private": True, "subnet_mask": "255.255.255.0",
                      "gateway": "192.168.1.1",
                  }]),
                  patch.object(network, "_read_state", return_value=saved),
                  patch.object(network, "_ip_helper_status", return_value="Running"),
                  patch.object(network, "_windows_listening_ports", return_value=set()),
                  patch.object(network, "_tcp_open", side_effect=lambda address, port: address != "192.168.1.12"),
                  patch.object(lan, "_firewall_exists", return_value=True),
                  patch.object(lan, "_verify_firewall"),
                  patch.object(lan, "_mapped_destination", return_value="172.19.225.173/80"),
                  patch.object(network, "_restart_ip_helper") as restart):
                result = CliRunner().invoke(app, ["network", "doctor"])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("no active Windows listener", result.output)
            self.assertIn("WSL backend", result.output)
            restart.assert_not_called()

    def test_native_linux_refresh_checks_tcp_without_windows_ip_helper(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            self.stack.installation.data_directory = Path(folder)
            self.stack.installation.runtime_type = "native"
            adapter = {"name": "eth0", "address": "192.168.1.12", "network": "192.168.1.0/24",
                       "category": "Host", "private": True}
            with (patch.object(network, "get_stack", return_value=self.stack),
                  patch.object(network, "inventory", return_value=[adapter]),
                  patch.object(network, "_tcp_open", return_value=False),
                  patch.object(network, "_restart_ip_helper") as restart):
                result = CliRunner().invoke(app, ["network", "refresh"])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("Native Linux", result.output)
            restart.assert_not_called()

    def test_native_linux_doctor_checks_https_lan_port_when_enabled(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            data = Path(folder)
            self.stack.installation.data_directory = data
            self.stack.installation.runtime_type = "native"
            (data / "tls.enabled").write_text("enabled")
            adapter = {"name": "eth0", "address": "192.168.1.12", "network": "192.168.1.0/24",
                       "category": "Host", "private": True, "subnet_mask": "255.255.255.0",
                       "gateway": "192.168.1.1"}
            with (patch.object(network, "get_stack", return_value=self.stack),
                  patch.object(network, "inventory", return_value=[adapter]),
                  patch.object(network, "_tcp_open", side_effect=lambda ip, port: port == 80),
                  patch.object(network, "_restart_ip_helper") as restart):
                result = CliRunner().invoke(app, ["network", "doctor"])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("192.168.1.12:443", result.output)
            restart.assert_not_called()

    def test_dns_config_not_claimed_router_verified(self):
        with patch.object(network_dns, "_service_exists", return_value=False):
            state = network_dns._status(self.stack)
        self.assertFalse(state["configured"])
        self.assertFalse(state["router_verified"])


if __name__ == "__main__":
    unittest.main()
