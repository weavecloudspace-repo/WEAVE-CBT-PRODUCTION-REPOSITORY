"""Exercise the self-update progress display under unittest on Windows and Linux."""

from __future__ import annotations

import io
import unittest

from weave_cli.progress import DownloadProgress


class InteractiveOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


class DownloadProgressTests(unittest.TestCase):
    def test_tty_updates_one_line_with_speed_and_eta(self):
        stream = InteractiveOutput()
        ticks = iter([0.0, 0.3, 0.6, 0.9]).__next__
        display = DownloadProgress(
            "weave-setup.exe", 4 * 1024 * 1024, stream=stream, clock=ticks
        )
        display.start()
        display.advance(2 * 1024 * 1024)
        display.advance(2 * 1024 * 1024)
        display.finish()
        output = stream.getvalue()
        self.assertGreaterEqual(output.count("\r"), 3)
        self.assertIn("50%", output)
        self.assertIn("100%", output)
        self.assertIn("MiB/s", output)
        self.assertIn("ETA", output)
        self.assertIn("Download complete:", output)

    def test_captured_output_throttles_percentages_without_carriage_returns(self):
        stream = io.StringIO()
        display = DownloadProgress(
            "installer.deb", 100, stream=stream, clock=lambda: 0.0
        )
        display.start()
        for _ in range(100):
            display.advance(1)
        display.finish()
        output = stream.getvalue()
        self.assertNotIn("\r", output)
        for percent in ("10%", "50%", "100%"):
            self.assertIn(percent, output)
        self.assertLessEqual(len(output.splitlines()), 15)

    def test_unknown_length_uses_spinner_without_fake_percentage(self):
        stream = InteractiveOutput()
        ticks = iter([0.0, 0.3, 0.6]).__next__
        display = DownloadProgress("installer.deb", None, stream=stream, clock=ticks)
        display.start()
        display.advance(1024)
        display.finish()
        output = stream.getvalue()
        self.assertIn("size unknown", output)
        self.assertNotIn("%", output)
        self.assertIn("Download complete", output)

    def test_plain_output_reports_unknown_size_without_terminal_escapes(self):
        stream = io.StringIO()
        tick = [0.0]
        display = DownloadProgress(
            "installer.deb", None, stream=stream, clock=lambda: tick[0]
        )
        display.start()
        display.advance(1024 * 1024)
        tick[0] = 5.1
        display.advance(1024 * 1024)
        display.finish()
        self.assertIn("size unknown", stream.getvalue())
        self.assertNotIn("\r", stream.getvalue())

    def test_abort_finishes_interactive_line_without_success_claim(self):
        stream = InteractiveOutput()
        ticks = iter([0.0, 0.3]).__next__
        display = DownloadProgress("installer.exe", 300, stream=stream, clock=ticks)
        display.start()
        display.advance(100)
        display.abort()
        output = stream.getvalue()
        self.assertTrue(output.endswith("\n"))
        self.assertNotIn("Download complete", output)

    def test_large_unknown_content_does_not_claim_percent_or_eta(self):
        stream = io.StringIO()
        display = DownloadProgress(
            "installer.exe", None, stream=stream, clock=lambda: 6.0
        )
        display.start()
        display.advance(8 * 1024 * 1024)
        display.finish()
        self.assertNotIn("%", stream.getvalue())
        self.assertNotIn("ETA", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
