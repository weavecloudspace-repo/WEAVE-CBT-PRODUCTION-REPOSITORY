"""Tests for isolated USB client hostname resolution, no real hosts writes."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner
from weave_cli.commands import client_resolution as client
from weave_cli.main import app

FIRST = {"schema": 1, "hostname": "first.school.cbt.weavecloudspace.com", "address": "192.168.1.10"}
SECOND = {"schema": 1, "hostname": "second.school.cbt.weavecloudspace.com", "address": "192.168.1.20"}


class ClientResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.hosts = self.root / "hosts"
        self.hosts.write_text("127.0.0.1 localhost\n# existing\n", encoding="utf-8")
        self.state = self.root / "state"

    def apply(self, config=FIRST, *, remove=False):
        return client.apply(config, hosts=self.hosts, state_dir=self.state, remove=remove)

    def test_cli_registration(self):
        result = CliRunner().invoke(app, ["network", "client", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("export", result.output)

    def test_new_mapping_preserves_unrelated_lines_and_state(self):
        self.assertTrue(self.apply())
        result = self.hosts.read_text(encoding="utf-8")
        self.assertIn("127.0.0.1 localhost", result)
        self.assertIn("# existing", result)
        self.assertIn("192.168.1.10 first.school.cbt.weavecloudspace.com", result)
        self.assertEqual(client._load_json(self.state / "config.json"), FIRST)
        self.assertEqual((self.state / "hosts.previous.bak").read_text(), "127.0.0.1 localhost\n# existing\n")

    def test_rerun_is_idempotent(self):
        self.apply()
        before = self.hosts.read_bytes()
        self.assertFalse(self.apply())
        self.assertEqual(self.hosts.read_bytes(), before)
        self.assertEqual(before.count(client.BEGIN.encode()), 1)

    def test_domain_change_replaces_previous_mapping(self):
        self.apply()
        self.apply(SECOND)
        content = self.hosts.read_text()
        self.assertNotIn(FIRST["hostname"], content)
        self.assertIn(SECOND["hostname"], content)
        self.assertEqual(content.count(client.BEGIN), 1)
        self.assertEqual(client._load_json(self.state / "config.json"), SECOND)

    def test_state_missing_can_reconcile_well_formed_owned_marker(self):
        self.apply()
        (self.state / "config.json").unlink()
        self.apply(SECOND)
        self.assertNotIn(FIRST["hostname"], self.hosts.read_text())

    def test_unmanaged_conflict_is_never_removed(self):
        self.hosts.write_text("127.0.0.1 localhost\n192.168.1.30 first.school.cbt.weavecloudspace.com\n")
        before = self.hosts.read_bytes()
        with self.assertRaises(client.ClientResolutionError):
            self.apply()
        self.assertEqual(self.hosts.read_bytes(), before)

    def test_conflicting_previous_state_fails_closed(self):
        self.apply()
        (self.state / "config.json").write_text(json.dumps(SECOND))
        before = self.hosts.read_bytes()
        with self.assertRaises(client.ClientResolutionError):
            self.apply(FIRST)
        self.assertEqual(self.hosts.read_bytes(), before)

    def test_malformed_markers_are_not_modified(self):
        self.hosts.write_text(client.BEGIN + "\n192.168.1.10 first.school.cbt.weavecloudspace.com\n")
        with self.assertRaises(client.ClientResolutionError):
            self.apply()

    def test_remove_is_scoped_and_idempotent(self):
        self.apply()
        self.assertTrue(self.apply(remove=True))
        self.assertEqual(self.hosts.read_text(), "127.0.0.1 localhost\n# existing\n")
        self.assertFalse((self.state / "config.json").exists())
        self.assertFalse(self.apply(remove=True))

    def test_write_failure_restores_hosts_and_state(self):
        self.apply()
        previous = self.hosts.read_bytes()
        old_state = (self.state / "config.json").read_bytes()
        original = client._atomic
        def fail_state_write(path, content, **kwargs):
            if path.name == "config.json":
                raise OSError("disk full")
            return original(path, content, **kwargs)
        with patch.object(client, "_atomic", side_effect=fail_state_write):
            with self.assertRaises(OSError):
                self.apply(SECOND)
        self.assertEqual(self.hosts.read_bytes(), previous)
        self.assertEqual((self.state / "config.json").read_bytes(), old_state)

    def test_validation_rejects_public_ip_and_invalid_hostname(self):
        for cfg in (
            {**FIRST, "address": "8.8.8.8"},
            {**FIRST, "hostname": "google.com"},
            {**FIRST, "hostname": "FIRST.school.cbt.weavecloudspace.com"},
            {**FIRST, "address": "192.168.001.10"},
        ):
            with self.subTest(cfg=cfg), self.assertRaises(client.ClientResolutionError):
                client.validated(cfg)

    def test_export_is_portable_with_config_and_executable(self):
        platform = "windows" if os.name == "nt" else "linux"
        name = "weave.exe" if platform == "windows" else "weave"
        binary = self.root / name
        binary.write_bytes(b"MZpayload" if platform == "windows" else b"\x7fELFpayload")
        archive = client.export_package(self.root / "usb", installation=self.root,
                                        hostname=FIRST["hostname"], address=FIRST["address"],
                                        platform=platform)
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()), {client.CONFIG_NAME,
                client.CLIENT_WINDOWS if platform == "windows" else client.CLIENT_LINUX})
            self.assertEqual(json.loads(z.read(client.CONFIG_NAME)), FIRST)

    def test_dns_flush_uses_system_command_without_manual_action(self):
        with patch.object(client.subprocess, "run") as run, \
             patch.object(client.shutil, "which", return_value="/usr/bin/resolvectl"):
            run.return_value.returncode = 0
            client._flush_dns()
        self.assertTrue(run.called)
        args = run.call_args.args[0]
        self.assertIn(args[0], ("ipconfig", "resolvectl"))

    def test_https_connectivity_failure_does_not_roll_back_mapping(self):
        self.apply()
        with patch.object(client.socket, "getaddrinfo", side_effect=OSError("offline")):
            client._verify(FIRST)
        self.assertIn(FIRST["hostname"], self.hosts.read_text())


if __name__ == "__main__":
    unittest.main()
