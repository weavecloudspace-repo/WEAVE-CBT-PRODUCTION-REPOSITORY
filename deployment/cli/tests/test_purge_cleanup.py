"""Host-level purge tests: no Docker, firewall, DNS, or portproxy mutations."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weave_cli.commands import lan, lan_tls, network_dns, purge_cleanup


class PurgeCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.data = root / "data"
        self.install = root / "install"
        self.data.mkdir()
        self.install.mkdir()
        self.stack = SimpleNamespace(installation=SimpleNamespace(
            runtime_type="wsl2", data_directory=self.data,
            install_directory=self.install
        ))
        self.record = {
            "listen_address": "192.168.1.12", "client_subnet": "192.168.1.0/24",
            "wsl_address": "172.19.225.173",
        }

    def test_removes_https_independently_when_http_state_is_missing(self):
        (self.data / "tls-lan.json").write_text(json.dumps(self.record))
        with patch.object(purge_cleanup, "remove_if_configured") as dns, \
             patch.object(lan_tls, "reconcile") as https, \
             patch.object(lan, "configure") as http:
            purge_cleanup.cleanup_host(self.stack)
        dns.assert_called_once_with(self.stack, purge_files=True)
        https.assert_called_once_with(self.data, remove=True)
        http.assert_not_called()

    def test_removes_http_and_https_via_existing_ownership_state(self):
        for filename in ("tls-lan.json", "lan.json"):
            (self.data / filename).write_text(json.dumps(self.record))
        with patch.object(purge_cleanup, "remove_if_configured"), \
             patch.object(lan_tls, "reconcile") as https, \
             patch.object(lan, "configure") as http:
            purge_cleanup.cleanup_host(self.stack)
        https.assert_called_once_with(self.data, remove=True)
        http.assert_called_once_with(self.data, remove=True)

    def test_unowned_current_wsl_https_mapping_blocks_purge_before_data_loss(self):
        with patch.object(purge_cleanup.sys, "platform", "win32"), \
             patch.object(lan, "_read_state", return_value=None), \
             patch("weave_cli.commands.network.inventory", return_value=[{
                 "address": "192.168.1.12", "private": True, "category": "Private",
             }]), \
             patch.object(lan, "_wsl_address", return_value="172.19.225.173"), \
             patch.object(lan, "_mapped_destination", return_value=None), \
             patch.object(lan_tls, "_destination", return_value="172.19.225.173/443"):
            with self.assertRaisesRegex(lan.LanError, "Unowned TCP/443"):
                purge_cleanup.preflight(self.stack)

    def test_unrelated_host_forwarding_is_never_deleted(self):
        with patch.object(purge_cleanup.sys, "platform", "win32"), \
             patch.object(lan, "_read_state", return_value=None), \
             patch("weave_cli.commands.network.inventory", return_value=[{
                 "address": "192.168.1.12", "private": True, "category": "Private",
             }]), \
             patch.object(lan, "_wsl_address", return_value="172.19.225.173"), \
             patch.object(lan, "_mapped_destination", return_value="172.18.0.50/80"), \
             patch.object(lan_tls, "_destination", return_value="172.18.0.50/443"), \
             patch.object(lan, "_firewall_exists", return_value=False), \
             patch.object(lan_tls, "_firewall_exists", return_value=False), \
             patch.object(network_dns, "_service_exists", return_value=False), \
             patch.object(lan, "_run") as netsh:
            state = purge_cleanup.preflight(self.stack)
        self.assertEqual(state.addresses, ())
        netsh.assert_not_called()

    def test_refuses_unowned_weave_firewall(self):
        with patch.object(purge_cleanup.sys, "platform", "win32"), \
             patch.object(lan, "_read_state", return_value=None), \
             patch("weave_cli.commands.network.inventory", return_value=[]), \
             patch.object(lan, "_wsl_address", return_value="172.19.225.173"), \
             patch.object(lan, "_firewall_exists", return_value=True):
            with self.assertRaisesRegex(lan.LanError, "firewall rule exists without"):
                purge_cleanup.preflight(self.stack)

    def test_rejects_symlink_active_config_instead_of_following_it(self):
        outside = self.data / "outside"
        outside.write_text("secret")
        (self.data / "runtime.env").symlink_to(outside)
        with self.assertRaisesRegex(lan.LanError, "Unsafe installation artifact"):
            purge_cleanup.clear_active_config(self.data, self.install)
        self.assertEqual(outside.read_text(), "secret")

    def test_clear_active_config_leaves_unknown_files_untouched(self):
        (self.data / "runtime.env").write_text("SECRET=fake")
        (self.data / "tls.enabled").write_text("enabled")
        (self.install / "compose.yaml").write_text("services: {}")
        (self.data / "do-not-delete").write_text("keep")
        purge_cleanup.clear_active_config(self.data, self.install)
        self.assertFalse((self.data / "runtime.env").exists())
        self.assertFalse((self.data / "tls.enabled").exists())
        self.assertFalse((self.install / "compose.yaml").exists())
        self.assertTrue((self.data / "do-not-delete").exists())

    def test_stale_dns_binary_removed_without_touching_unknown_files(self):
        dns_dir = self.data / "dns"
        dns_dir.mkdir()
        (dns_dir / "Corefile").write_text("stale configuration")
        (dns_dir / "records.hosts").write_text("stale DNS record")
        (self.install / "coredns.exe").write_text("stale binary")
        (dns_dir / "operator-notes.txt").write_text("preserve")
        purge_cleanup.clear_dns_artifacts(self.data, self.install)
        self.assertFalse((dns_dir / "Corefile").exists())
        self.assertFalse((dns_dir / "records.hosts").exists())
        self.assertFalse((self.install / "coredns.exe").exists())
        self.assertTrue((dns_dir / "operator-notes.txt").exists())

    def test_verify_does_not_delete_or_reject_unrelated_tcp80_on_https_only(self):
        snapshot = purge_cleanup.HostSnapshot(
            addresses=("192.168.1.12",), runtime_type="wsl2",
            https_addresses=("192.168.1.12",),
        )
        with patch.object(purge_cleanup.sys, "platform", "win32"), \
             patch.object(lan_tls, "_destination", return_value=None), \
             patch.object(lan, "_mapped_destination", return_value="172.18.0.50/80") as http, \
             patch.object(lan, "_firewall_exists", return_value=False), \
             patch.object(lan_tls, "_firewall_exists", return_value=False), \
             patch.object(network_dns, "_service_exists", return_value=False):
            purge_cleanup.verify_host(self.stack, snapshot)
        http.assert_not_called()

    def test_full_uninstall_file_cleanup_removes_update_journal(self):
        (self.data / "update-recovery.json").write_text('{"phase": "pending"}')
        (self.data / ".cbt-update.lock").write_text("stale")
        purge_cleanup.clear_active_config(self.data, self.install)
        self.assertFalse((self.data / "update-recovery.json").exists())
        self.assertFalse((self.data / ".cbt-update.lock").exists())

    def test_windows_owned_coredns_files_removed_only_during_full_purge(self):
        dns = self.data / "dns"
        dns.mkdir()
        corefile = dns / "Corefile"
        records = dns / "records.hosts"
        marker = dns / "managed.json"
        binary = self.install / "coredns.exe"
        for file in (corefile, records, binary):
            file.write_text("weave managed")
        marker.write_text(json.dumps({
            "schema": 1, "executable": str(binary), "address": "192.168.1.12"
        }))
        with patch.object(network_dns, "_status", return_value={
            "configured": True, "service_registered": True,
        }), patch.object(network_dns, "_service_action") as service, \
             patch.object(network_dns.lan, "_powershell"):
            network_dns.remove_if_configured(self.stack, purge_files=True)
        self.assertFalse(marker.exists())
        self.assertFalse(corefile.exists())
        self.assertFalse(records.exists())
        self.assertFalse(binary.exists())
        self.assertTrue(any(c.args[0] == "delete" for c in service.call_args_list))


if __name__ == "__main__":
    unittest.main()
