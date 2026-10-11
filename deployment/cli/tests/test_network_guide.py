"""Read-only network guide never accesses secrets or mutates the host."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weave_cli.commands import network_guide


class NetworkGuideTests(unittest.TestCase):
    def test_no_lan_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                network_guide._configured_lan(Path(root)), (None, None)
            )

    def test_extracts_only_expected_public_lan_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "lan.json").write_text(json.dumps({
                "listen_address": "192.168.10.10",
                "client_subnet": "192.168.10.0/24",
                "private_token": "must-never-be-displayed",
            }), encoding="utf-8")
            self.assertEqual(
                network_guide._configured_lan(path),
                ("192.168.10.10", "192.168.10.0/24"),
            )
            with patch.object(network_guide, "_configured_lan", return_value=(
                "192.168.10.10", "192.168.10.0/24"
            )), patch.object(network_guide.typer, "echo") as output:
                with patch.object(network_guide.sys, "platform", "win32"), patch.dict(
                    network_guide.os.environ, {"ProgramData": root}
                ):
                    network_guide.network_guide()
            shown = "\n".join(str(call.args[0]) for call in output.call_args_list)
            self.assertIn("192.168.10.10", shown)
            self.assertNotIn("must-never-be-displayed", shown)
            self.assertIn("read-only", shown)


if __name__ == "__main__":
    unittest.main()
