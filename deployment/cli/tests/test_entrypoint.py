"""Smoke tests for the single WEAVE CBT Typer entrypoint."""

import re
import unittest
from typer.testing import CliRunner

from weave_cli.main import app


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_root_help_exposes_all_nine_commands(self):
        result = self.runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        for name in (
            "install", "start", "stop", "restart", "status",
            "logs", "doctor", "update", "uninstall",
        ):
            self.assertIn(name, result.output)

    def test_install_help_does_not_run_installer(self):
        result = self.runner.invoke(app, ["install", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--env-file", re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.output))

    def test_logs_help_exposes_follow_flag(self):
        result = self.runner.invoke(app, ["logs", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--follow", re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.output))

    def test_unknown_command_is_rejected(self):
        result = self.runner.invoke(app, ["unknown-command"])
        self.assertEqual(result.exit_code, 2)


if __name__ == "__main__":
    unittest.main()
