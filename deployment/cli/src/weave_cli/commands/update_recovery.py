"""Durable recovery state for local image-and-database updates.

The snapshot is a local PostgreSQL TEMPLATE copy, not an Alembic downgrade.
Recovering it intentionally discards writes made since the snapshot.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterator

PHASES = frozenset({"preparing", "pending", "restored", "ready"})


@dataclass(frozen=True)
class UpdateRecovery:
    previous_image: str
    target_image: str
    previous_version: str
    snapshot_database: str
    failed_database: str
    phase: str = "preparing"


def recovery_path(data_directory: Path) -> Path:
    return data_directory / "update-recovery.json"


def read_recovery(path: Path) -> UpdateRecovery | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = UpdateRecovery(**raw)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(
            "Update recovery state is damaged. Do not start CBT or overwrite it; "
            f"inspect {path}."
        ) from exc
    if (
        record.phase not in PHASES
        or not all(
            isinstance(value, str) and value
            for value in asdict(record).values()
        )
    ):
        raise RuntimeError("Invalid update recovery state; refusing unsafe recovery.")
    return record


def save_recovery(path: Path, record: UpdateRecovery) -> None:
    """Atomically persist a non-secret journal before changing image or schema."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".cbt-update-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            json.dump(asdict(record), output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def mark_phase(path: Path, record: UpdateRecovery, phase: str) -> UpdateRecovery:
    if phase not in PHASES:
        raise ValueError("Invalid recovery phase")
    updated = replace(record, phase=phase)
    save_recovery(path, updated)
    return updated


def guard_pending_update(data_directory: Path) -> None:
    record = read_recovery(recovery_path(data_directory))
    if record is not None and record.phase != "ready":
        raise RuntimeError(
            "An image/database update was interrupted. Run 'weave rollback' "
            "before starting or restarting CBT."
        )


@contextmanager
def update_lock(data_directory: Path) -> Iterator[None]:
    """Serialize CLI update and rollback operations on the installed machine."""
    lock_path = data_directory / ".cbt-update.lock"
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            "Another CBT update or rollback is in progress (or was interrupted). "
            f"Inspect the installation before clearing {lock_path}."
        ) from exc
    try:
        os.close(handle)
        yield
    finally:
        lock_path.unlink(missing_ok=True)
