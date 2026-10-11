"""Best-effort, human-readable local error archives. Live Compose logging is retained."""
from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RULE = "=" * 48
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PARTS = 12
SECRET = re.compile(r"(?i)(password|token|secret|api[_-]?key|authorization|access[_-]?code)(\s*[:=]\s*)([^\s,;]+)")
BEARER = re.compile(r"(?i)\bBearer\s+\S+")
CREDENTIAL = re.compile(r"(://[^:/@\s]+:)[^@\s/]+(@)")
SQL_PARAMS = re.compile(r"(?is)\[parameters:\s*.*?\]")
SQL_TEXT = re.compile(r"(?is)\[SQL:\s*.*?\]")


def redact(value: object) -> str:
    text = SECRET.sub(r"\1\2<redacted>", str(value))
    text = BEARER.sub("Bearer <redacted>", text)
    text = CREDENTIAL.sub(r"\1<redacted>\2", text)
    text = SQL_PARAMS.sub("[parameters: <redacted>]", text)
    return SQL_TEXT.sub("[SQL: <redacted>]", text)


def segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)[:64] or "unknown"


def format_error(record: logging.LogRecord, service: str) -> str:
    at = datetime.fromtimestamp(record.created, UTC)
    try:
        local = at.astimezone(ZoneInfo("Africa/Lagos"))
    except (OSError, KeyError):
        local = at
    failure = record.exc_info[1] if record.exc_info else None
    location = f"{record.pathname}:{record.lineno} ({record.funcName})"
    trace = "No traceback provided."
    if record.exc_info:
        import traceback
        frames = traceback.extract_tb(record.exc_info[2])
        if frames:
            last = frames[-1]
            location = f"{last.filename}:{last.lineno} ({last.name})"
        trace = redact("".join(traceback.format_exception(*record.exc_info)))
    identifier = f"ERR-{at.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    reason = redact(f"{type(failure).__name__}: {failure}") if failure else "No exception details supplied."
    return (
        f"{RULE}\nWEAVE CBT  |  ERROR REPORT\n{RULE}\n\n"
        f"Timestamp:    {at.isoformat()} (UTC)\n"
        f"Local time:   {local.strftime('%d %B %Y, %I:%M:%S %p')}\n"
        f"Service:      {service}\nSeverity:     {record.levelname}\n"
        f"Error ID:     {identifier}\n"
        f"Instance:     {segment(os.environ.get('HOSTNAME', 'local'))}\n\n"
        f"WHAT HAPPENED\n{'-' * 48}\n{redact(record.getMessage())}\n\n"
        f"WHY IT FAILED\n{'-' * 48}\n{reason}\n\n"
        f"ERROR DETAILS\n{'-' * 48}\n"
        f"Operation: {redact(getattr(record, 'operation', record.funcName))}\n"
        f"Request ID: {redact(getattr(record, 'request_id', 'not available'))}\n"
        f"Job ID: {redact(getattr(record, 'job_id', 'not available'))}\n\n"
        f"WHERE THE ERROR OCCURRED\n{'-' * 48}\n{redact(location)}\n\n"
        f"TECHNICAL TRACEBACK\n{'-' * 48}\n{trace}\n\n"
        f"RECOVERY STATUS\n{'-' * 48}\n"
        f"{redact(getattr(record, 'recovery_status', 'Not confirmed'))}\n\n"
        f"{RULE}\nEND OF ERROR {identifier}\n{RULE}\n\n"
    )


class ErrorArchiveHandler(logging.Handler):
    def __init__(self, root: Path, service: str):
        super().__init__(logging.ERROR)
        self.root = root
        self.service = segment(service)
        self.instance = segment(os.environ.get("HOSTNAME", "local"))

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return
        try:
            data = format_error(record, self.service).encode("utf-8", "replace")
            day = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%d")
            folder = self.root / self.service / day
            folder.mkdir(parents=True, mode=0o700, exist_ok=True)
            for part in range(MAX_PARTS):
                suffix = f"-{part:02d}" if part else ""
                file = folder / f"{self.instance}-errors{suffix}.log"
                if file.is_symlink():
                    raise OSError("Log archive path must not be a symbolic link.")
                if file.exists() and file.stat().st_size + len(data) > MAX_FILE_BYTES:
                    continue
                flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(file, flags, 0o600)
                with os.fdopen(descriptor, "ab") as output:
                    output.write(data)
                break
            else:
                raise OSError("Daily error archive limit exceeded.")
        except Exception as exc:  # noqa: BLE001 - error archive must never crash the API
            # A missing/full disk must never fail an examination request or job.
            try:
                sys.stderr.write(f"WEAVE CBT archive unavailable: {type(exc).__name__}\n")
                sys.stderr.write(redact(record.getMessage()) + "\n")
            except Exception:  # noqa: BLE001 - even stderr can become unavailable
                return


def prune_own_service(root: Path, service: str) -> None:
    folder = root / segment(service)
    if folder.is_symlink() or not folder.is_dir():
        return
    cutoff = datetime.now(UTC).date() - timedelta(days=30)
    for directory in folder.iterdir():
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            day = date.fromisoformat(directory.name)
        except ValueError:
            continue
        if day >= cutoff:
            continue
        for file in directory.iterdir():
            if file.is_file() and not file.is_symlink() and file.name.endswith(".log"):
                file.unlink()
        if not any(directory.iterdir()):
            directory.rmdir()


def configure_error_logging(service: str) -> None:
    location = os.environ.get("WEAVE_LOG_DIR", "").strip()
    if not location:
        return
    root = Path(location)
    if not root.is_absolute():
        sys.stderr.write("WEAVE CBT archive directory must be absolute.\n")
        return
    handler = ErrorArchiveHandler(root, service)
    for logger in (logging.getLogger(), logging.getLogger("uvicorn.error"), logging.getLogger("arq.worker")):
        if not any(isinstance(existing, ErrorArchiveHandler) for existing in logger.handlers):
            logger.addHandler(handler)
    try:
        prune_own_service(root, service)
    except OSError:
        sys.stderr.write("WEAVE CBT could not prune old error archives.\n")
