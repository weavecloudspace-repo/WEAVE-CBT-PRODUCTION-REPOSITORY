"""Regression: compiled CLI startup must work with legacy Windows code pages."""
import os
import subprocess
import sys
import unittest
from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.py"


class WindowsCliEncodingTests(unittest.TestCase):
    def test_cli_help_with_cp1252_redirected_streams(self):
        environment = dict(os.environ)
        environment["PYTHONIOENCODING"] = "cp1252"
        process = subprocess.run(
            [sys.executable, str(ENTRYPOINT), "--help"],
            env=environment, capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(
            process.returncode, 0, process.stderr.decode("utf-8", errors="replace")
        )
        self.assertIn("install", process.stdout.decode("utf-8"))
        self.assertIn("lan", process.stdout.decode("utf-8"))

    def test_cli_error_stream_with_cp1252_redirected_streams(self):
        environment = dict(os.environ)
        environment["PYTHONIOENCODING"] = "cp1252"
        process = subprocess.run(
            [sys.executable, str(ENTRYPOINT), "lan", "--help"],
            env=environment, capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(
            process.returncode, 0, process.stderr.decode("utf-8", errors="replace")
        )


if __name__ == "__main__":
    unittest.main()
