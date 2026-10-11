"""Unit checks for local error archives; no database or Docker access required."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.core.error_logging import ErrorArchiveHandler, redact


def record(message: str, *, level: int = logging.ERROR) -> logging.LogRecord:
    event = logging.makeLogRecord(
        {
            "name": "test.archive",
            "levelno": level,
            "levelname": logging.getLevelName(level),
            "pathname": "results.py",
            "lineno": 184,
            "funcName": "sync_exam_results",
            "msg": message,
            "args": (),
            "created": datetime(2026, 10, 11, 16, 42, tzinfo=UTC).timestamp(),
        }
    )
    return event


def test_error_archive_creates_dated_per_instance_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOSTNAME", "api-2")
    handler = ErrorArchiveHandler(tmp_path, "api")
    handler.emit(record("Synchronization failed: token=abc123"))
    files = list((tmp_path / "api" / "2026-10-11").glob("*.log"))
    assert len(files) == 1
    assert files[0].name == "api-2-errors.log"
    content = files[0].read_text()
    assert "WEAVE CBT  |  ERROR REPORT" in content
    assert "WHAT HAPPENED" in content
    assert "WHERE THE ERROR OCCURRED" in content
    assert "WHY IT FAILED" in content
    assert "2026-10-11T16:42:00+00:00" in content
    assert "token=<redacted>" in content
    assert "abc123" not in content


def test_warnings_not_archived(tmp_path: Path):
    ErrorArchiveHandler(tmp_path, "worker").emit(
        record("Not an error", level=logging.WARNING)
    )
    assert not list(tmp_path.rglob("*.log"))


def test_log_write_failures_never_raise(tmp_path: Path):
    conflict = tmp_path / "not-a-directory"
    conflict.write_text("occupied")
    ErrorArchiveHandler(conflict, "api").emit(record("Failure"))


def test_redacts_sensitive_patterns():
    result = redact(
        "authorization=Bearer_test secret=something "
        "Bearer abcd postgresql://weave:pw123@postgres:5432/cbt "
        "[parameters: ('student', 72)] [SQL: INSERT INTO attempts]"
    )
    for secret in ("something", "abcd", "pw123", "'student'", "INSERT INTO"):
        assert secret not in result
