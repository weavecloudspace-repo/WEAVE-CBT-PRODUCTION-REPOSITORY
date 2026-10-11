"""Persistent local log reader and CLI contracts, without a Docker daemon."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner
from weave_cli.commands import logs
from weave_cli.commands.error_archive import get_error_records
from weave_cli.main import app


class ArchiveTests(unittest.TestCase):
    def test_read_only_report_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            folder = data / "service-logs" / "api" / "2026-10-11"
            folder.mkdir(parents=True)
            report = (
                "=" * 48 + "\nWEAVE CBT  |  ERROR REPORT\n"
                + "=" * 48 + "\n"
                + "Timestamp:    2026-10-11T16:42:00+00:00 (UTC)\n"
                + "WHAT HAPPENED\nConnection lost.\n"
                + "END OF ERROR ERR-20261011-01\n" + "=" * 48
            )
            (folder / "api-1-errors.log").write_text(report, encoding="utf-8")
            self.assertEqual(len(get_error_records(data, service="api", limit=3)), 1)
            self.assertEqual(get_error_records(data, service="worker"), [])
            with self.assertRaises(ValueError):
                get_error_records(data, service="../../etc")
            with self.assertRaises(ValueError):
                get_error_records(data, day="11-10-2026")

    def test_invalid_cli_combinations_rejected(self):
        runner = CliRunner()
        for args in (
            ["logs", "--errors", "--follow"],
            ["logs", "--last", "3"],
            ["logs", "--errors", "--date", "2026/10/11"],
        ):
            with self.subTest(args=args), patch.object(logs, "get_stack") as stack:
                result = runner.invoke(app, args)
                self.assertEqual(result.exit_code, 2, result.output)
                stack.assert_not_called()

    def test_network_help_appears_in_main_cli(self):
        result = CliRunner().invoke(app, ["network", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("doctor", result.output)
        self.assertIn("recommend", result.output)
        self.assertIn("configure", result.output)


if __name__ == "__main__":
    unittest.main()
