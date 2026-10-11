"""Regression tests for the desktop-to-CLI process boundary.

Run on Linux and Windows; compiled onefile acceptance runs separately on Windows.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class CliProcessTests(unittest.TestCase):
    def setUp(self):
        bridge.clear_cli_verification_cache()

    def test_nuitka_onefile_variables_are_not_forwarded(self):
        original = {
            "_NUITKA_ONEFILE_PARENT": "unrelated-gui-process",
            "_NUITKA_ONEFILE_BINARY": "unrelated-gui.exe",
            "NUITKA_ONEFILE_PARENT": "legacy-parent",
            "WEAVE_TEST_KEEP": "expected",
        }
        with patch.dict(os.environ, original):
            child = bridge.cli_subprocess_environment()
        self.assertEqual(child["WEAVE_TEST_KEEP"], "expected")
        for name in original:
            if "NUITKA_ONEFILE" in name:
                self.assertNotIn(name, child)
        self.assertIn("WEAVE_TEST_KEEP", os.environ) if "WEAVE_TEST_KEEP" in os.environ else None

    def test_cli_failure_is_retried_and_success_cached(self):
        with tempfile.TemporaryDirectory() as root:
            exe = Path(root) / "weave.exe"
            exe.touch()
            failed = subprocess.CompletedProcess([str(exe), "release"], 1, "", "temporary failure")
            passed = subprocess.CompletedProcess([str(exe), "release"], 0, "verified", "")
            with patch.object(bridge.subprocess, "run", side_effect=[failed, passed]) as run:
                first = bridge.verify_cli(exe, windows=True)
                second = bridge.verify_cli(exe, windows=True)
                third = bridge.verify_cli(exe, windows=True)
            self.assertFalse(first.valid)
            self.assertIn("exit code 1", first.problem)
            self.assertTrue(second.valid)
            self.assertTrue(third.valid)
            self.assertEqual(run.call_count, 2)
            self.assertIn("env", run.call_args.kwargs)

    def test_timeout_is_reported_and_not_cached(self):
        with tempfile.TemporaryDirectory() as root:
            exe = Path(root) / "weave.exe"
            exe.touch()
            timeout = subprocess.TimeoutExpired([str(exe), "release"], 12)
            with patch.object(bridge.subprocess, "run", side_effect=timeout) as run:
                first = bridge.verify_cli(exe, windows=True)
                second = bridge.verify_cli(exe, windows=True)
            self.assertFalse(first.valid)
            self.assertIn("timed out", first.problem)
            self.assertEqual(run.call_count, 2)

    def test_failed_release_output_is_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as root:
            exe = Path(root) / "weave.exe"
            exe.touch()
            failure = subprocess.CompletedProcess(
                [str(exe), "release"], 1, "password=do-not-expose",
                "token=do-not-expose " + "x" * 2000,
            )
            with patch.object(bridge.subprocess, "run", return_value=failure):
                result = bridge.verify_cli(exe, windows=True)
            self.assertNotIn("do-not-expose", result.problem)
            self.assertLess(len(result.problem), 900)

    def test_windows_candidate_includes_installed_gui_sibling(self):
        with tempfile.TemporaryDirectory() as root:
            gui = Path(root) / "WEAVE-CBT-Desktop.exe"
            with patch.object(bridge.sys, "argv", [str(gui)]), \
                 patch.dict(os.environ, {"ProgramFiles": str(Path(root) / "Other")}), \
                 patch.object(bridge.shutil, "which", return_value=None):
                options = bridge.candidates(windows=True)
            self.assertIn(Path(root) / "weave.exe", options)


if __name__ == "__main__":
    unittest.main()
