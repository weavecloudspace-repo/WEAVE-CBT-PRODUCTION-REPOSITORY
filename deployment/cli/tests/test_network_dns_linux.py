"""Linux CoreDNS lifecycle verification without systemd, DNS, or internet side effects."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weave_cli.commands import network_dns_linux as dns


class LinuxDNSTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stack = SimpleNamespace(
            installation=SimpleNamespace(runtime_type="native", data_directory=self.root),
            platform=SimpleNamespace(is_admin=lambda: True),
        )
        self.adapter = {
            "name": "eth0", "address": "192.168.1.12",
            "network": "192.168.1.0/24", "category": "Host",
            "private": True,
        }

    def test_no_pairing_refuses_dns_install(self):
        with self.assertRaisesRegex(dns.DNSError, "activate HTTPS"):
            dns._identity(self.stack, None)

    def test_unit_is_boot_persistent_and_isolated(self):
        text = dns._unit_text(self.root / "dns")
        self.assertIn("WantedBy=multi-user.target", text)
        self.assertIn("ProtectSystem=strict", text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("ExecStart=", text)

    def test_unowned_unit_is_never_overwritten(self):
        unit = self.root / "foreign.service"
        unit.write_text("# not WEAVE\n", encoding="utf-8")
        (self.root / "tls.enabled").write_text("enabled\n", encoding="utf-8")
        with patch.object(dns, "UNIT_FILE", unit), \
             patch.object(dns, "_identity", return_value=("host.school.cbt.weavecloudspace.com", self.adapter)), \
             patch.object(dns, "_check_dns_port"):
            with self.assertRaisesRegex(dns.DNSError, "without WEAVE ownership"):
                dns.setup_linux(self.stack)
        self.assertEqual(unit.read_text(), "# not WEAVE\n")

    def test_service_status_does_not_claim_router_verified(self):
        with patch.object(dns, "UNIT_FILE", self.root / "missing.service"):
            status = dns._snapshot(self.stack)
        self.assertFalse(status["configured"])
        self.assertFalse(status["router_verified"])

    def test_identity_requires_valid_private_adapter(self):
        (self.root / "tls.enabled").write_text("enabled\n", encoding="utf-8")
        with patch("weave_cli.commands.network._https_hostname",
                   return_value="host.school.cbt.weavecloudspace.com"), \
             patch.object(dns.network, "inventory", return_value=[self.adapter]):
            hostname, selected = dns._identity(self.stack, "eth0")
        self.assertEqual(hostname, "host.school.cbt.weavecloudspace.com")
        self.assertEqual(selected["address"], "192.168.1.12")


if __name__ == "__main__":
    unittest.main()
