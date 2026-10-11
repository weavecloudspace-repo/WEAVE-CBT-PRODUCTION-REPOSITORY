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

    def test_dns_config_not_claimed_router_verified(self):
        with patch.object(network_dns, "_service_exists", return_value=False):
            state = network_dns._status(self.stack)
        self.assertFalse(state["configured"])
        self.assertFalse(state["router_verified"])


if __name__ == "__main__":
    unittest.main()
