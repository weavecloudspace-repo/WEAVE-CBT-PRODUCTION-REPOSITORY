"""Read persistent error archives from the registered CBT data directory."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

SERVICES = frozenset(("api", "worker", "bootstrap", "postgres", "redis", "nginx"))
START = re.compile(r"(?=^={48}\nWEAVE CBT  \|  ERROR REPORT\n)", re.MULTILINE)
TIMESTAMP = re.compile(r"(?m)^Timestamp:\s+(\S+)")


def get_error_records(data_directory: Path, service: str | None = None,
                      day: str | None = None, limit: int = 20) -> list[str]:
    if service is not None and service not in SERVICES:
        raise ValueError("Unknown service.")
    if day is not None:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Date must use YYYY-MM-DD.")
    if not 1 <= limit <= 100:
        raise ValueError("Report limit must be between 1 and 100.")
    root = data_directory / "service-logs"
    records: list[tuple[str, str]] = []
    for name in ([service] if service else sorted(SERVICES)):
        directory = root / name
        if directory.is_symlink() or not directory.is_dir():
            continue
        days = [day] if day else sorted(
            (p.name for p in directory.iterdir() if p.is_dir() and not p.is_symlink()
             and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)),
            reverse=True,
        )[:3]
        for folder_name in days:
            folder = directory / folder_name
            if folder.is_symlink() or not folder.is_dir():
                continue
            for file in folder.iterdir():
                if file.is_symlink() or not file.is_file():
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_-]+-errors(?:-\d{2})?\.log", file.name):
                    continue
                with file.open("rb") as stream:
                    stream.seek(0, 2)
                    stream.seek(max(0, stream.tell() - 2 * 1024 * 1024))
                    content = stream.read().decode("utf-8", "replace")
                for report in START.split(content):
                    if not report.startswith("=" * 48 + "\nWEAVE CBT  |  ERROR REPORT"):
                        continue
                    stamp = TIMESTAMP.search(report)
                    if stamp and "\nEND OF ERROR " in report:
                        records.append((stamp.group(1), report.strip()))
    return [report for _, report in sorted(records, reverse=True)[:limit]]
