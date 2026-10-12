"""Read-only network detection; never change real host interfaces/firewall."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from weave_cli.commands import network
from weave_cli.main import app


class NetworkInventoryTests(unittest.TestCase):
    def setUp(self):
        self.adapter = {
            "name": "Ethernet",
            "address": "192.168.10.24",
            "subnet_mask": "255.255.255.0",
            "network": "192.168.10.0/24",
            "gateway": "192.168.10.1",
            "category": "Private",
            "private": True,
        }

    def test_recommend_one_private_eligible_adapter(self):
        self.assertEqual(network.recommend([self.adapter]), self.adapter)
        self.assertIsNone(network.recommend([self.adapter, self.adapter]))
        public = dict(self.adapter, address="8.8.8.8", private=False)
        self.assertIsNone(network.recommend([public]))
        broad = dict(self.adapter, network="192.168.0.0/16")
        self.assertIsNone(network.recommend([broad]))
        untrusted = dict(self.adapter, category="Public")
        self.assertIsNone(network.recommend([untrusted]))
        reserved = dict(self.adapter, network="198.18.10.0/24")
        self.assertIsNone(network.recommend([reserved]))
        virtual = dict(self.adapter, name="vEthernet (WSL)")
        self.assertIsNone(network.recommend([virtual]))

    def test_auto_recommends_detected_larger_school_subnet(self):
        for prefix, subnet in (
            (23, "192.168.10.0/23"),
            (22, "192.168.8.0/22"),
            (21, "192.168.8.0/21"),
            (20, "192.168.0.0/20"),
        ):
            with self.subTest(prefix=prefix):
                adapter = dict(self.adapter, network=subnet)
                self.assertEqual(network.recommend([adapter]), adapter)
                self.assertEqual(network._candidate([adapter], "Ethernet"), adapter)

    def test_windows_adapter_inventory_uses_actual_detected_prefix(self):
        with (
            patch.object(network.sys, "platform", "win32"),
            patch.object(network, "_windows_addresses", return_value=[{
                "name": "Ethernet", "address": "192.168.10.24",
                "prefix": 22, "gateway": "192.168.10.1", "category": "Private",
            }]),
        ):
            found = network.inventory()
        self.assertEqual(found[0]["network"], "192.168.8.0/22")
        self.assertEqual(found[0]["subnet_mask"], "255.255.252.0")
        self.assertEqual(found[0]["gateway"], "192.168.10.1")

    def test_linux_skips_virtual_bridge_and_calculates_netmask(self):
        result = [
            {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
            {"ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1", "prefixlen": 16}]},
            {"ifname": "eth0", "addr_info": [{"family": "inet", "local": "192.168.10.24", "prefixlen": 24}]},
        ]
        with (
            patch.object(network.sys, "platform", "linux"),
            patch.object(network, "_run", side_effect=[
                json.dumps(result),
                json.dumps([{"dev": "eth0", "gateway": "192.168.10.1"}]),
            ]),
        ):
            found = network.inventory()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["network"], "192.168.10.0/24")
        self.assertEqual(found[0]["subnet_mask"], "255.255.255.0")
        self.assertEqual(found[0]["gateway"], "192.168.10.1")

    def test_cli_json_inventory_is_read_only(self):
        with patch.object(network, "inventory", return_value=[self.adapter]):
            result = CliRunner().invoke(app, ["network", "info", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        self.assertEqual(data["recommended"]["address"], "192.168.10.24")
        self.assertEqual(data["interfaces"][0]["network"], "192.168.10.0/24")


if __name__ == "__main__":
    unittest.main()
