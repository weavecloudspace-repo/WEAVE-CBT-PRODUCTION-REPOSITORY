"""Transactional and least-privilege HTTPS LAN forwarding tests (no Windows host)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weave_cli.commands import lan_tls


class TLSLanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.address = "192.168.1.10"
        self.subnet = "192.168.1.0/24"
        self.old = "172.22.1.4"
        self.new = "172.22.1.5"
        self.base = {
            "listen_address": self.address,
            "client_subnet": self.subnet,
            "wsl_address": self.old,
        }

    def _scoped(self):
        patches = [
            patch.object(lan_tls.lan, "_read_state", return_value=self.base),
            patch.object(lan_tls.lan, "_assert_private_interface"),
            patch.object(lan_tls.lan, "_wsl_address", return_value=self.new),
            patch.object(lan_tls, "_destination", return_value=None),
            patch.object(lan_tls, "_firewall_exists", return_value=False),
            patch.object(lan_tls, "_create_firewall"),
            patch.object(lan_tls, "_verify_firewall"),
            patch.object(lan_tls.lan, "_run"),
            patch.object(lan_tls.lan, "_powershell"),
        ]
        mocks = [item.start() for item in patches]
        for item in patches:
            self.addCleanup(item.stop)
        return mocks

    def test_configures_and_persists_only_scoped_listener(self):
        mocks = self._scoped()
        lan_tls.reconcile(self.data)
        state = json.loads((self.data / "tls-lan.json").read_text())
        self.assertEqual(state, {
            "listen_address": self.address,
            "client_subnet": self.subnet,
            "wsl_address": self.new,
        })
        mocks[5].assert_called_once_with(self.address, self.subnet)
        mocks[6].assert_called_once_with(self.address, self.subnet)
        args = mocks[7].call_args.args[0]
        self.assertEqual(args[-2:], ["connectport=443", f"connectaddress={self.new}"])

    def test_failed_persistence_rolls_back_firewall_and_mapping(self):
        mocks = self._scoped()
        with patch.object(lan_tls, "_save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                lan_tls.reconcile(self.data)
        self.assertFalse((self.data / "tls-lan.json").exists())
        self.assertEqual(mocks[7].call_count, 2)
        self.assertIn("add", mocks[7].call_args_list[0].args[0])
        self.assertIn("delete", mocks[7].call_args_list[1].args[0])
        self.assertIn("Remove-NetFirewallRule", mocks[8].call_args.args[0])

    def test_failed_refresh_restores_old_wsl_forwarding(self):
        mocks = self._scoped()
        (self.data / "tls-lan.json").write_text(json.dumps(self.base))
        mocks[3].return_value = self.old + "/443"
        with patch.object(lan_tls, "_save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                lan_tls.reconcile(self.data)
        operations = [call.args[0] for call in mocks[7].call_args_list]
        self.assertEqual([operation[5] for operation in operations], [
            "listenport=443", "listenport=443", "listenport=443", "listenport=443"
        ])
        self.assertEqual([operation[3] for operation in operations], [
            "delete", "add", "delete", "add"
        ])
        self.assertIn(f"connectaddress={self.old}", operations[-1])
        mocks[5].assert_called_once_with(self.address, self.subnet)  # newly created firewall is compensated

    def test_refuses_an_unowned_existing_https_mapping(self):
        mocks = self._scoped()
        mocks[3].return_value = self.new + "/443"
        with self.assertRaisesRegex(lan_tls.lan.LanError, "ownership state"):
            lan_tls.reconcile(self.data)
        mocks[7].assert_not_called()
        mocks[5].assert_not_called()

    def test_rejects_extra_firewall_remote_scope(self):
        bad_rule = {
            "Direction": "Inbound", "Action": "Allow", "Enabled": "True",
            "Profile": "Private,Domain", "Protocol": "TCP",
            "Port": ["443"], "Address": [self.address],
            "Remote": [self.subnet, "192.168.2.0/24"],
        }
        with patch.object(lan_tls.lan, "_powershell", return_value=json.dumps(bad_rule)):
            with self.assertRaises(lan_tls.lan.LanError):
                lan_tls._verify_firewall(self.address, self.subnet)

    def test_rejects_public_firewall_profile(self):
        bad_rule = {
            "Direction": "Inbound", "Action": "Allow", "Enabled": "True",
            "Profile": "Public", "Protocol": "TCP",
            "Port": ["443"], "Address": [self.address],
            "Remote": [self.subnet],
        }
        with patch.object(lan_tls.lan, "_powershell", return_value=json.dumps(bad_rule)):
            with self.assertRaises(lan_tls.lan.LanError):
                lan_tls._verify_firewall(self.address, self.subnet)


if __name__ == "__main__":
    unittest.main()
