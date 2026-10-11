"""Unit tests for transfer progress in real and captured terminals."""

from __future__ import annotations

import io

from weave_cli.progress import DownloadProgress


class InteractiveOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_tty_updates_single_line_and_shows_statistics():
    stream = InteractiveOutput()
    clock = iter([0.0, 0.3, 0.6, 0.9]).__next__
    display = DownloadProgress("weave-setup.exe", 4 * 1024 * 1024, stream=stream, clock=clock)
    display.start()
    display.advance(2 * 1024 * 1024)
    display.advance(2 * 1024 * 1024)
    display.finish()
    text = stream.getvalue()
    assert text.count("\r") >= 3
    assert "50%" in text
    assert "100%" in text
    assert "MiB/s" in text
    assert "ETA" in text
    assert "Download complete:" in text


def test_captured_output_throttles_progress_and_never_uses_carriage_returns():
    stream = io.StringIO()
    tick = [0.0]

    def clock() -> float:
        return tick[0]

    display = DownloadProgress("installer.deb", 100, stream=stream, clock=clock)
    display.start()
    for _ in range(100):
        display.advance(1)
    display.finish()
    text = stream.getvalue()
    assert "\r" not in text
    assert "10%" in text
    assert "100%" in text
    assert len(text.splitlines()) <= 15


def test_unknown_length_uses_spinner_without_false_percentages():
    stream = InteractiveOutput()
    tick = iter([0.0, 0.3, 0.6]).__next__
    display = DownloadProgress("installer.deb", None, stream=stream, clock=tick)
    display.start()
    display.advance(1024)
    display.finish()
    text = stream.getvalue()
    assert "size unknown" in text
    assert "%" not in text
    assert "Download complete" in text


def test_plain_output_reports_unknown_size_without_terminal_escapes():
    stream = io.StringIO()
    tick = [0.0]

    def clock() -> float:
        return tick[0]

    display = DownloadProgress("installer.deb", None, stream=stream, clock=clock)
    display.start()
    display.advance(1024 * 1024)
    tick[0] = 5.1
    display.advance(1024 * 1024)
    display.finish()
    assert "size unknown" in stream.getvalue()
    assert "\r" not in stream.getvalue()
