"""Upgrade installed deployment assets when the *new* CLI first starts.

The old manager has no awareness of newer Compose or Nginx files. This module
stages packaged assets, journals originals, validates Compose and rolls back on
failure. It deliberately does not alter WSL mode, certificates, or exam data.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

ASSETS = (
    "compose.yaml",
    "nginx/nginx.conf",
    "nginx/reload-watch.sh",
    "certificates/hooks.py",
)
RECORD = "deployment-assets.json"
JOURNAL = "deployment-upgrade.json"
BACKUP = "deployment-upgrade-backup"


class DeploymentUpgradeError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_bytes(target: Path, payload: bytes) -> None:
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise DeploymentUpgradeError("Unsafe managed asset: " + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".weave-asset-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: dict) -> None:
    _atomic_bytes(path, (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def _paths(stack) -> tuple[Path, Path]:
    return stack.installation.install_directory, stack.installation.data_directory


def pending(stack) -> bool:
    """Read-only check; does not require Docker or mutate installation state."""
    from weave_cli.commands.install import _assets_root, _read_release_manifest
    install, data = _paths(stack)
    if (data / JOURNAL).exists():
        return True
    assets = _assets_root(None)
    if _read_release_manifest(assets) is None:
        return False  # Source checkouts may not have a packaged release.
    return any(
        (assets / p).is_file()
        and ((not (install / p).is_file()) or _digest(assets / p) != _digest(install / p))
        for p in ASSETS
    )


def _restore(stack, journal: dict) -> None:
    install, data = _paths(stack)
    backup = data / BACKUP
    for relative in journal["changed"]:
        old = backup / relative
        target = install / relative
        if old.is_file() and not old.is_symlink():
            _atomic_bytes(target, old.read_bytes())
        elif relative in journal["created"]:
            target.unlink(missing_ok=True)
        else:
            raise DeploymentUpgradeError("Missing backup for " + relative)
    stack.compose.config()


def ensure_current(stack) -> bool:
    """Apply a first-start upgrade. Return True if Compose assets were changed.

    The installed Compose project and its volumes remain unchanged. Callers
    perform 'compose up -d' after True: plain 'restart' ignores new definitions.
    """
    from weave_cli.commands.install import _assets_root, _read_release_manifest
    from weave_cli.networking.state import load_or_import
    install, data = _paths(stack)
    assets = _assets_root(None)
    manifest = _read_release_manifest(assets)
    if manifest is None:
        return False
    if not stack.platform.is_admin():
        if pending(stack):
            raise DeploymentUpgradeError("Run weave start as Administrator to upgrade managed assets.")
        return False

    # Keep the legacy NAT listener and previous HTTPS state. Import without
    # silently granting persistent profile trust or enabling remote access.
    load_or_import(data, runtime_type=stack.installation.runtime_type)

    journal_path = data / JOURNAL
    if journal_path.exists():
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if sorted(journal["changed"]) != sorted(set(journal["changed"])):
                raise ValueError("Duplicate recorded paths")
            if not set(journal["changed"]).issubset(ASSETS):
                raise ValueError("Unknown changed asset")
            _restore(stack, journal)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise DeploymentUpgradeError(
                "Incomplete deployment upgrade; cannot verify backup. Manual recovery required."
            ) from exc
        _finish_journal(data, journal)

    changes = [
        p for p in ASSETS
        if (assets / p).is_file()
        and (not (install / p).is_file() or _digest(assets / p) != _digest(install / p))
    ]
    if not changes:
        return False

    backup = data / BACKUP
    if backup.exists():
        raise DeploymentUpgradeError("Existing deployment backup requires inspection.")
    backup.mkdir(mode=0o700, parents=True)
    created = []
    try:
        for relative in changes:
            target = install / relative
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise DeploymentUpgradeError("Unsafe managed asset: " + relative)
            if target.exists():
                original = backup / relative
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, original)
            else:
                created.append(relative)
        journal = {"changed": changes, "created": created, "version": manifest["version"]}
        _atomic_json(journal_path, journal)
        for relative in changes:
            _atomic_bytes(install / relative, (assets / relative).read_bytes())
        stack.compose.config()
        # Delay commit until the caller's Compose up and health checks pass.
        return True
    except Exception:
        if journal_path.exists():
            _restore(stack, journal)
            _finish_journal(data, journal)
        elif backup.is_dir():
            shutil.rmtree(backup)
        raise


def _finish_journal(data: Path, journal: dict) -> None:
    (data / JOURNAL).unlink(missing_ok=True)
    backup = data / BACKUP
    if backup.is_dir() and not backup.is_symlink():
        shutil.rmtree(backup)


def commit(stack) -> None:
    install, data = _paths(stack)
    journal_path = data / JOURNAL
    if not journal_path.is_file():
        return
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    _atomic_json(data / RECORD, {
        "manager_version": journal["version"],
        "checksums": {p: _digest(install / p) for p in ASSETS},
    })
    _finish_journal(data, journal)


def rollback(stack) -> None:
    data = stack.installation.data_directory
    journal_path = data / JOURNAL
    if not journal_path.exists():
        return
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    _restore(stack, journal)
    _finish_journal(data, journal)
