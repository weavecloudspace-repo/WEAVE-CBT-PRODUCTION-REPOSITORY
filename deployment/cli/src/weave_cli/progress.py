"""Dependency-free CLI download progress for interactive and captured consoles.

TTY output redraws one line. Captured output (including the Desktop Manager's
QProcess) gets throttled, newline-delimited progress without terminal escapes.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TextIO


def _size(value: float) -> str:
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / (1024 * 1024):.1f} MiB"


def _eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes:02d}:{remainder:02d}"


class DownloadProgress:
    """Display transfer progress, not an unverified installation success."""

    def __init__(
        self,
        filename: str,
        total_bytes: int | None,
        *,
        stream: TextIO | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.filename = filename
        self.total_bytes = total_bytes if total_bytes and total_bytes > 0 else None
        self.stream = stream if stream is not None else sys.stdout
        self.clock = clock if clock is not None else time.monotonic
        self.interactive = bool(getattr(self.stream, "isatty", lambda: False)())
        self.downloaded = 0
        self.started: float | None = None
        self.last_render = 0.0
        self.last_report_percent = 0
        self.last_report_time = 0.0
        self.frame = 0
        self.line_width = 0
        self.finished = False

    def start(self) -> None:
        if self.started is not None:
            return
        self.started = self.clock()
        self.last_report_time = self.started
        self.stream.write(f"Downloading {self.filename}...\n")
        if self.interactive:
            self._render(self.started)
        self.stream.flush()

    def advance(self, count: int) -> None:
        if self.started is None:
            self.start()
        self.downloaded += count
        now = self.clock()
        if self.interactive:
            if now - self.last_render >= 0.12:
                self._render(now)
        elif self.total_bytes is not None:
            percent = min(100, int(100 * self.downloaded / self.total_bytes))
            if percent >= self.last_report_percent + 10 or now - self.last_report_time >= 5:
                self._report(now)
                self.last_report_percent = (percent // 10) * 10
                self.last_report_time = now
        elif now - self.last_report_time >= 5:
            self._report(now)
            self.last_report_time = now

    def _description(self, now: float) -> str:
        elapsed = max(now - (self.started if self.started is not None else now), 0.001)
        rate = self.downloaded / elapsed
        speed = f"{_size(rate)}/s"
        if self.total_bytes is not None:
            fraction = min(self.downloaded / self.total_bytes, 1)
            percentage = int(100 * fraction)
            filled = min(24, int(24 * fraction))
            bar = "#" * filled + "-" * (24 - filled)
            remaining = _eta((self.total_bytes - self.downloaded) / rate) if rate > 0 else "--:--"
            return (
                f"[{bar}] {percentage:3d}%  "
                f"{_size(self.downloaded)} / {_size(self.total_bytes)}  "
                f"{speed}  ETA {remaining}"
            )
        frames = "|/-\\"
        spinner = frames[self.frame % len(frames)]
        self.frame += 1
        return f"{spinner} {_size(self.downloaded)} downloaded  {speed}  (size unknown)"

    def _render(self, now: float) -> None:
        line = self._description(now)
        self.stream.write("\r" + line + " " * max(0, self.line_width - len(line)))
        self.stream.flush()
        self.line_width = len(line)
        self.last_render = now

    def _report(self, now: float) -> None:
        self.stream.write(self._description(now) + "\n")
        self.stream.flush()

    def finish(self) -> None:
        if self.finished:
            return
        if self.started is None:
            self.start()
        if self.interactive:
            self._render(self.clock())
            self.stream.write("\n")
        self.stream.write(f"Download complete: {_size(self.downloaded)} transferred.\n")
        self.stream.flush()
        self.finished = True

    def abort(self) -> None:
        """Terminate a partially drawn TTY line before an error is reported."""
        if not self.finished and self.interactive and self.started is not None:
            self.stream.write("\n")
            self.stream.flush()
        self.finished = True
