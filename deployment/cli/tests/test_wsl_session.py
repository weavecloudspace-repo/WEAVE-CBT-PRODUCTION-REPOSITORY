"""Validate task scripts without registering tasks or starting WSL."""

import base64
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

from weave_cli.platforms.base import PlatformError
from weave_cli.platforms.wsl_session import manage_session, task_script


class WslSessionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell required")
    def test_owner_names_resolve_to_sid_and_foreign_owner_is_rejected(self):
        # Mock task discovery/removal only; resolve real Windows account identities.
        cases = (
            ("$identity.Name", 0),
            ("$identity.User.Value", 0),
            ("($identity.Name -split '\\\\')[-1]", 0),
            ("'S-1-5-18'", 1),
        )
        for owner, expected in cases:
            script = (
                "$identity = [Security.Principal.WindowsIdentity]::GetCurrent(); "
                f"$script:testOwner = {owner}; "
                "function Get-ScheduledTask { param($TaskName, $ErrorAction) "
                "[pscustomobject]@{ Principal = [pscustomobject]@{ UserId = $script:testOwner } } }; "
                "function Stop-ScheduledTask { param($TaskName) }; "
                "function Unregister-ScheduledTask { param($TaskName, $Confirm) }; "
                "try {\n" + task_script("WeaveCBT", remove=True)
                + "\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
            )
            payload = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text",
                 "-EncodedCommand", payload],
                capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            if expected:
                self.assertIn("another Windows user", result.stderr)
                self.assertNotIn("CLIXML", result.stderr)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell required")
    def test_generated_scripts_parse_in_windows_powershell(self):
        for distribution in ("WeaveCBT", "School's WSL"):
            setup = task_script(distribution)
            keeper = base64.b64decode(
                re.search(r"-EncodedCommand ([A-Za-z0-9+/=]+)", setup).group(1)
            ).decode("utf-16le")
            for script in (setup, keeper, task_script(distribution, remove=True)):
                # Parse only: no host mutations, scheduled tasks, or WSL processes.
                payload = base64.b64encode(script.encode("utf-16le")).decode("ascii")
                parser = (
                    "$source = [Text.Encoding]::Unicode.GetString("
                    f"[Convert]::FromBase64String('{payload}')); "
                    "$tokens = $null; $parseErrors = $null; "
                    "[void][Management.Automation.Language.Parser]::ParseInput("
                    "$source, [ref]$tokens, [ref]$parseErrors); "
                    "if ($parseErrors.Count) { $parseErrors | Out-String | Write-Output; exit 1 }"
                )
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", parser],
                    capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_task_failure_is_reported(self):
        with patch("weave_cli.platforms.wsl_session.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "Access denied"
            with self.assertRaisesRegex(PlatformError, "Access denied"):
                manage_session("WeaveCBT")

    def test_timeout_is_reported(self):
        with (
            patch("weave_cli.platforms.wsl_session.subprocess.run",
                  side_effect=subprocess.TimeoutExpired("powershell.exe", 45)),
            self.assertRaises(PlatformError),
        ):
            manage_session("WeaveCBT")


if __name__ == "__main__":
    unittest.main()
