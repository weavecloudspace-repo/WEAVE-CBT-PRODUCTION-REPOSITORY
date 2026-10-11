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
