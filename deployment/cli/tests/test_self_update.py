"""Offline checks for channel-pinned verified manager upgrades."""
from __future__ import annotations

import hashlib
import io
import unittest
from pathlib import Path

import typer
from typer.testing import CliRunner
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

    def test_download_progress_preserves_checksum_and_size_verification(self):
        payload = b"WEAVE verified update contents"
        correct = hashlib.sha256(payload).hexdigest()
        release = {"tag_name": "staging-1.0.2", "assets": []}
        for declared_size in (str(len(payload)), None):
            with self.subTest(length=declared_size), patch.object(
                self_update, "_official_asset", return_value="https://github.com/fake"
            ), patch.object(self_update, "urlopen", return_value=_Response(payload, declared_size)), patch(
                "weave_cli.progress.sys.stdout", new_callable=io.StringIO
            ) as output:
                result = self_update._download_verified(release, "installer.deb", correct)
                try:
                    self.assertEqual(result.read_bytes(), payload)
                    self.assertIn("Download complete:", output.getvalue())
                finally:
                    result.unlink()
                    result.parent.rmdir()

    def test_truncated_download_rejected_even_if_its_checksum_matches(self):
        payload = b"partial"
        expected = hashlib.sha256(payload).hexdigest()
        with patch.object(
            self_update, "_official_asset", return_value="https://github.com/fake"
        ), patch.object(
            self_update, "urlopen", return_value=_Response(payload, "99")
        ), patch("weave_cli.progress.sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(self_update.ManagerUpdateError, "Incomplete installer download"):
                self_update._download_verified({}, "installer.deb", expected)

    def test_invalid_length_does_not_invent_percentage(self):
        self.assertIsNone(self_update._declared_download_size(_Response(b"abc", None)))
        self.assertIsNone(self_update._declared_download_size(_Response(b"abc", "invalid")))
        self.assertIsNone(self_update._declared_download_size(_Response(b"abc", "0")))
        self.assertEqual(self_update._declared_download_size(_Response(b"abc", "3")), 3)

    def test_hash_mismatch_still_rejects_update(self):
        with patch.object(
            self_update, "_official_asset", return_value="https://github.com/fake"
        ), patch.object(
            self_update, "urlopen", return_value=_Response(b"payload", "7")
        ), patch("weave_cli.progress.sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(self_update.ManagerUpdateError, "SHA-256"):
                self_update._download_verified({}, "installer.deb", "0" * 64)

    def _run_windows_update(self, arguments):
        app = typer.Typer()
        self_update.register(app)

        @app.command("other")
        def other():
            pass

        installer = Path("C:/Temp/verified/WEAVE-CBT-Staging-Desktop-Setup.exe")
        release = {"tag_name": "staging-1.0.1502"}
        with (
            patch.object(self_update.sys, "platform", "win32"),
            patch.object(self_update, "_assets_root", return_value=Path("C:/WeaveCBT/assets")),
            patch.object(self_update, "_read_release_manifest", return_value={
                "channel": "staging", "version": "1.0.1501",
            }),
            patch.object(self_update, "_latest", return_value=release),
            patch.object(self_update, "_expected_hash", return_value="a" * 64),
            patch.object(self_update, "_download_verified", return_value=installer) as download,
            patch.object(self_update.os, "startfile", create=True) as launch,
            patch.object(self_update.os, "getpid", return_value=9123),
        ):
            result = CliRunner().invoke(app, ["self-update", *arguments])
            calls = list(launch.call_args_list)
            downloaded = download.call_count
        return result, calls, downloaded, installer

    def test_windows_gui_update_passes_gui_pid_to_admin_installer(self):
        result, calls, downloaded, installer = self._run_windows_update(
            ["--yes", "--manager-pid", "44221"]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(downloaded, 1)
        self.assertEqual(calls[0].args, (str(installer), "runas", "/WEAVEPID=44221"))
        self.assertIn("WEAVE_MANAGER_INSTALLER_LAUNCHED", result.output)

    def test_windows_cli_update_waits_for_exiting_cli_process(self):
        result, calls, _, installer = self._run_windows_update(["--yes"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(calls[0].args, (str(installer), "runas", "/WEAVEPID=9123"))

    def test_rejects_invalid_manager_pid_before_downloading(self):
        for pid in ("0", "-1", "4294967296"):
            with self.subTest(pid=pid):
                result, calls, downloaded, _ = self._run_windows_update(
                    ["--yes", "--manager-pid", pid]
                )
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("Invalid Desktop Manager update handoff", result.output)
                self.assertEqual(downloaded, 0)
                self.assertEqual(calls, [])

    def test_update_check_does_not_launch_installer_or_emit_handoff(self):
        result, calls, downloaded, _ = self._run_windows_update(["--check"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(downloaded, 0)
        self.assertEqual(calls, [])
        self.assertNotIn("WEAVE_MANAGER_INSTALLER_LAUNCHED", result.output)

    def test_rejects_unofficial_download_host(self):
        release = {"tag_name": "staging-1.0.1501", "assets": [{
            "name": "SHA256SUMS",
            "browser_download_url": "https://attacker.invalid/fake"
        }]}
        with self.assertRaises(self_update.ManagerUpdateError):
            self_update._official_asset(release, "SHA256SUMS")


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, length: str | None):
        super().__init__(payload)
        self.headers = {"Content-Length": length} if length is not None else {}

