"""TLS and school-DNS regression coverage for WSL NAT vs mirrored transports.

Tests mock Docker and Windows firewall calls; nothing changes the test host.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import typer

from weave_cli.commands import tls, network_dns
from weave_cli.commands.network_mirrored import MirroredFirewallError
from weave_cli.networking import state


HOSTNAME = "node.school.cbt.weavecloudspace.com"
ADDRESS = "192.168.1.44"
SUBNET = "192.168.1.0/24"


def make_stack(data: Path, transport: str = "mirrored"):
    policy = state.load_or_import(data, runtime_type="wsl2")
    policy.update(
        transport=transport,
        address=ADDRESS,
        subnet=SUBNET,
        interface_name="Ethernet",
        interface_guid="{4DAE214D-2B4A-45D1-8E23-0B55633209F3}",
        restore_private=True,
    )
    state.save(data, policy)
    return SimpleNamespace(
        installation=SimpleNamespace(data_directory=data, runtime_type="wsl2"),
        platform=SimpleNamespace(is_admin=lambda: True),
        runtime=SimpleNamespace(docker_engine_running=lambda: True),
        compose=Mock(),
    )


class MirroredTlsTests(unittest.TestCase):
    def setUp(self):
        # GitHub Windows test runners use a legacy stdout encoding; mock only
        # presentation so the tests exercise TLS behavior, not console glyphs.
        for name in ("banner", "info", "success"):
            active = patch.object(tls, name)
            active.start()
            self.addCleanup(active.stop)
        failed = patch.object(tls, "fail", side_effect=typer.Exit(code=1))
        failed.start()
        self.addCleanup(failed.stop)

    def test_first_tls_issuance_uses_mirrored_firewall_without_nat_lan_or_portproxy(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            self.assertFalse((data / "lan.json").exists())
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch("weave_cli.commands.network_mirrored.configure") as firewall,
                patch("weave_cli.commands.lan_tls.reconcile") as nat_https,
                patch("weave_cli.commands.network_dns.reconcile_if_configured") as dns,
            ):
                tls.tls(dry_run=False, renew=False, activate=False)
            self.assertTrue((data / "tls.enabled").is_file())
            firewall.assert_called_once()
            self.assertIs(firewall.call_args.args[0], stack)
            self.assertEqual(firewall.call_args.args[1]["transport"], "mirrored")
            nat_https.assert_not_called()
            dns.assert_called_once_with(stack)
            self.assertFalse((data / "tls-lan.json").exists())
            commands = [call.kwargs["command"]
                        for call in stack.compose._run_compose_command.call_args_list]
            self.assertIn(
                ["--profile", "tls-issue", "run", "--rm", "--no-deps", "certbot"],
                commands,
            )

    def test_existing_certificate_activation_does_not_create_nat_portproxy(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch("weave_cli.commands.network_mirrored.configure") as firewall,
                patch("weave_cli.commands.lan_tls.reconcile") as nat_https,
                patch("weave_cli.commands.network_dns.reconcile_if_configured"),
            ):
                tls.tls(dry_run=False, renew=False, activate=True)
            firewall.assert_called_once()
            nat_https.assert_not_called()
            self.assertTrue((data / "tls.enabled").is_file())
            commands = [call.kwargs["command"]
                        for call in stack.compose._run_compose_command.call_args_list]
            self.assertFalse(any("certbot" in command for command in commands))

    def test_rejected_mirrored_firewall_stops_before_certbot_or_tls_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch("weave_cli.commands.network_mirrored.configure",
                      side_effect=MirroredFirewallError("school adapter identity changed")),
            ):
                with self.assertRaises(typer.Exit):
                    tls.tls(dry_run=False, renew=False, activate=False)
            stack.compose._run_compose_command.assert_not_called()
            self.assertFalse((data / "tls.enabled").exists())

    def test_nat_without_lan_still_refuses_issuance_before_certbot(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data, transport="nat")
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch("weave_cli.commands.network_mirrored.configure") as firewall,
            ):
                with self.assertRaises(typer.Exit):
                    tls.tls(dry_run=False, renew=False, activate=False)
            firewall.assert_not_called()
            stack.compose._run_compose_command.assert_not_called()
            self.assertFalse((data / "tls.enabled").exists())

    def test_nat_with_lan_retains_owned_https_portproxy_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data, transport="nat")
            (data / "lan.json").write_text("{}", encoding="utf-8")
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch("weave_cli.commands.network_mirrored.configure") as firewall,
                patch("weave_cli.commands.lan_tls.reconcile") as nat_https,
                patch("weave_cli.commands.network_dns.reconcile_if_configured"),
            ):
                tls.tls(dry_run=False, renew=False, activate=False)
            firewall.assert_not_called()
            nat_https.assert_called_once_with(data)
            self.assertTrue((data / "tls.enabled").exists())

    def test_mirrored_tls_renewal_does_not_reconfigure_host_firewall(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            (data / "tls.enabled").write_text("enabled\n", encoding="utf-8")
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch("weave_cli.commands.network_mirrored.configure") as firewall,
                patch("weave_cli.commands.lan_tls.reconcile") as nat_https,
                patch("weave_cli.commands.network_dns.reconcile_if_configured"),
            ):
                tls.tls(dry_run=False, renew=True, activate=False)
            firewall.assert_not_called()
            nat_https.assert_not_called()

    def test_mirrored_school_dns_uses_approved_adapter_without_nat_state(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            (data / "tls.enabled").write_text("enabled\n", encoding="utf-8")
            with (
                patch.object(network_dns.sys, "platform", "win32"),
                patch("weave_cli.commands.network_mirrored._approved",
                      return_value=(ADDRESS, SUBNET, "Ethernet")) as approved,
                patch("weave_cli.commands.network._https_hostname", return_value=HOSTNAME),
                patch.object(network_dns.lan, "_read_state") as nat,
            ):
                result = network_dns._get_ip_and_hostname(stack)
            self.assertEqual(result, (HOSTNAME, ADDRESS, SUBNET))
            approved.assert_called_once()
            nat.assert_not_called()

    def test_nat_school_dns_still_uses_saved_forwarding_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data, transport="nat")
            (data / "tls.enabled").write_text("enabled\n", encoding="utf-8")
            with (
                patch.object(network_dns.sys, "platform", "win32"),
                patch.object(network_dns.lan, "_read_state", return_value={
                    "listen_address": ADDRESS,
                    "client_subnet": SUBNET,
                    "wsl_address": "172.19.1.12",
                }) as nat,
                patch("weave_cli.commands.network._https_hostname", return_value=HOSTNAME),
                patch("weave_cli.commands.network_mirrored._approved") as mirror,
            ):
                result = network_dns._get_ip_and_hostname(stack)
            self.assertEqual(result, (HOSTNAME, ADDRESS, SUBNET))
            nat.assert_called_once_with(data)
            mirror.assert_not_called()

    def test_mirrored_dns_cannot_fallback_to_nat_when_approval_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            (data / "tls.enabled").write_text("enabled\n", encoding="utf-8")
            with (
                patch.object(network_dns.sys, "platform", "win32"),
                patch("weave_cli.commands.network_mirrored._approved",
                      side_effect=MirroredFirewallError("untrusted school adapter")),
                patch.object(network_dns.lan, "_read_state") as nat,
            ):
                with self.assertRaisesRegex(MirroredFirewallError, "untrusted"):
                    network_dns._get_ip_and_hostname(stack)
            nat.assert_not_called()


    def test_mirrored_network_url_returns_student_https_without_nat_mapping(self):
        from typer.testing import CliRunner
        from weave_cli.main import app
        from weave_cli.commands import network
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            with (
                patch.object(network, "get_stack", return_value=stack),
                patch.object(network, "_read_state") as nat,
                patch.object(network, "_https_hostname", return_value=HOSTNAME),
            ):
                result = CliRunner().invoke(app, ["network", "url", "--json"])
            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["address"], ADDRESS)
            self.assertEqual(payload["url"], "https://" + HOSTNAME + "/student")
            nat.assert_not_called()

    def test_mirrored_network_status_displays_approved_ip_without_nat_mapping(self):
        from typer.testing import CliRunner
        from weave_cli.main import app
        from weave_cli.commands import network
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            with (
                patch.object(network, "get_stack", return_value=stack),
                patch.object(network, "inventory", return_value=[]),
                patch.object(network, "_read_state") as nat,
            ):
                result = CliRunner().invoke(app, ["network", "status", "--json"])
            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["transport"], "mirrored")
            self.assertEqual(payload["school_network"]["listen_address"], ADDRESS)
            self.assertEqual(payload["school_network"]["client_subnet"], SUBNET)
            nat.assert_not_called()

    def test_mirrored_network_url_rejects_unapproved_interface(self):
        from typer.testing import CliRunner
        from weave_cli.main import app
        from weave_cli.commands import network
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = make_stack(data)
            policy = state.load(data)
            policy["restore_private"] = False
            state.save(data, policy)
            with (
                patch.object(network, "get_stack", return_value=stack),
                patch.object(network, "_read_state") as nat,
            ):
                result = CliRunner().invoke(app, ["network", "url", "--json"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("prefer set", result.output)
            nat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
