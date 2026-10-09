"""Verify Windows console installer commands without touching machine PATH/UAC."""
import base64
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SETUP_PATH = Path(__file__).resolve().parents[2] / "distribution" / "windows" / "setup.py"
spec = importlib.util.spec_from_file_location("weave_windows_console_setup", SETUP_PATH)
assert spec is not None and spec.loader is not None
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class WindowsInstallerContractTests(unittest.TestCase):
    def test_elevation_uses_native_powershell_51_without_gui_wizard(self):
        completed = subprocess.CompletedProcess(args=[], returncode=23)
        with (
            patch.object(setup.subprocess, "run", return_value=completed) as run,
            patch.object(setup.sys, "argv", [r"C:\Downloads\WEAVE-CBT-Setup.exe"]),
            patch.object(setup.sys, "executable", r"C:\Downloads\WEAVE-CBT-Setup.exe"),
        ):
            self.assertEqual(setup.request_elevation_and_wait(), 23)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ["powershell.exe", "-NoProfile", "-NonInteractive"])
        self.assertEqual(argv[3], "-EncodedCommand")
        script = base64.b64decode(argv[4]).decode("utf-16le")
        self.assertIn("Start-Process", script)
        self.assertIn("WEAVE-CBT-Setup.exe", script)
        self.assertIn("-Verb RunAs -Wait -PassThru", script)
        self.assertIn("exit $child.ExitCode", script)
        self.assertNotIn("ShellExecuteW", script)

    def test_payload_verification_skips_administrator_elevation(self):
        with (
            patch.object(setup.sys, "platform", "win32"),
            patch.object(setup.sys, "argv", ["WEAVE-CBT-Setup.exe", "--verify-payload"]),
            patch.object(setup, "perform_install") as verify,
            patch.object(setup, "admin", side_effect=AssertionError("Should not request elevation")),
        ):
            self.assertEqual(setup.main(), 0)
            verify.assert_called_once_with(verify_only=True)

    def test_installer_exits_immediately_on_non_windows_hosts(self):
        with patch.object(setup.sys, "platform", "linux"):
            self.assertEqual(setup.main(), 1)

    @unittest.skipUnless(sys.platform == "win32", "Native PowerShell syntax validation on Windows CI")
    def test_encoded_uac_script_parses_in_windows_powershell(self):
        with patch.object(
            setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ) as run:
            setup.request_elevation_and_wait()
        encoded = run.call_args.args[0][4]
        text = base64.b64decode(encoded).decode("utf-16le")
        # Use Windows PowerShell's parser without calling Start-Process or UAC.
        quoted = text.replace("'", "''")
        validation = (
            "$t=$null;$e=$null;"
            "[System.Management.Automation.Language.Parser]::ParseInput('"
            + quoted + "',[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count -gt 0){exit 1}"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(validation.encode("utf-16le")).decode("ascii")],
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
