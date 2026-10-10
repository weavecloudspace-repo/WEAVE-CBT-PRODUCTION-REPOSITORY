"""Offline checks for channel-pinned verified manager upgrades."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from weave_cli.commands import self_update


class ManagerUpdateTests(unittest.TestCase):
    def test_strict_version_parser(self):
        self.assertEqual(self_update._version("staging-1.0.1501"), (1, 0, 1501))
        self.assertEqual(self_update._version("v1.0.1501"), (1, 0, 1501))
        self.assertEqual(self_update._version("1.0.1501"), (1, 0, 1501))
        with self.assertRaises(self_update.ManagerUpdateError):
            self_update._version("staging-1x0x1501")

    def test_staging_never_selects_production_release(self):
        source = [
            {"tag_name": "v1.0.2000", "prerelease": False, "draft": False},
            {"tag_name": "staging-1.0.1501", "prerelease": True, "draft": False},
            {"tag_name": "staging-1.0.1502", "prerelease": True, "draft": False},
        ]
        import json
        with patch.object(self_update, "_get", return_value=json.dumps(source).encode()):
            self.assertEqual(self_update._latest("staging")["tag_name"], "staging-1.0.1502")
            self.assertEqual(self_update._latest("production")["tag_name"], "v1.0.2000")

    def test_rejects_unofficial_download_host(self):
        release = {"tag_name": "staging-1.0.1501", "assets": [{
            "name": "SHA256SUMS",
            "browser_download_url": "https://attacker.invalid/fake"
        }]}
        with self.assertRaises(self_update.ManagerUpdateError):
            self_update._official_asset(release, "SHA256SUMS")
