"""Read-only CLI discovery and installation-state detection for the desktop manager.

This module deliberately has no GUI dependencies, making it testable on both OSes.
Never mistake finding weave.exe for a successfully installed CBT server.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Discovery:
    cli: Path | None
    installation: dict | None
    problem: str = ""

    @property
    def manager_installed(self) -> bool:
        return self.cli is not None

    @property
    def server_installed(self) -> bool:
        return self.installation is not None


def state_path(*, windows: bool | None = None) -> Path:
    if windows is None:
        windows = sys.platform == "win32"
    if windows:
        return Path(os.getenv("ProgramData", r"C:\ProgramData")) / "WeaveCBT" / "install.json"
    return Path("/var/lib/weave-cbt/install.json")


def candidates(*, windows: bool | None = None, packaged: Path | None = None) -> list[Path]:
    if windows is None:
        windows = sys.platform == "win32"
    name = "weave.exe" if windows else "weave"
    roots = (
        [Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "WeaveCBT" / name]
        if windows else [Path("/usr/bin/weave"), Path("/usr/local/bin/weave")]
    )
    on_path = shutil.which(name)
    if on_path:
        roots.append(Path(on_path))
    if packaged:
        roots.append(packaged / "payload" / name)
    return list(dict.fromkeys(roots))


@lru_cache(maxsize=32)
def _verified_cli(path: str, modified_ns: int, *, windows: bool) -> bool:
    try:
        check = subprocess.run(
            [path, "release"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=12,
            **({"creationflags": subprocess.CREATE_NO_WINDOW}
               if windows and sys.platform == "win32" else {}),
        )
        return check.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def discover(*, windows: bool | None = None, packaged: Path | None = None) -> Discovery:
    cli = None
    issue = ""
    for candidate in candidates(windows=windows, packaged=packaged):
        if not candidate.is_file():
            continue
        try:
            valid = _verified_cli(
                str(candidate), candidate.stat().st_mtime_ns,
                windows=windows if windows is not None else sys.platform == "win32")
            if valid:
                cli = candidate
                break
            issue = f"Found CLI at {candidate}, but its release check failed."
        except OSError as exc:
            issue = f"CLI metadata is unreadable: {exc}"
    path = state_path(windows=windows)
    installation = None
    try:
        state_available = path.is_file()
        # Root-owned Linux installation state may be unreadable to the GUI.
        # Distinguish that from a genuinely absent installation.
        path.stat()
    except FileNotFoundError:
        state_available = False
    except PermissionError:
        state_available = False
        issue = "CBT installation state requires Administrator access. Run a privileged diagnostic before installing."
    if state_available:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (isinstance(raw, dict)
                    and raw.get("schema_version") == 1
                    and isinstance(raw.get("installed_version"), str)
                    and isinstance(raw.get("install_directory"), str)
                    and isinstance(raw.get("data_directory"), str)
                    and (Path(raw["install_directory"]) / "compose.yaml").is_file()
                    and (Path(raw["data_directory"]) / "runtime.env").is_file()):
                installation = raw
            else:
                issue = "Existing CBT installation state is incomplete. Run diagnostics."
        except (OSError, ValueError) as exc:
            issue = f"Cannot read CBT installation state: {exc}"
    return Discovery(cli, installation, issue)


def is_admin() -> bool:
    if sys.platform == "win32":
        import ctypes
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def elevate_gui(operation: str, arguments: list[str] | None = None) -> bool:
    """Relaunch only when user requests an administrative action; no silent elevation."""
    if is_admin():
        return True
    if sys.platform == "win32":
        import ctypes
        import subprocess as sp
        program = str(Path(sys.argv[0]).resolve())
        parameters = sp.list2cmdline(["--elevated", "--auto-command", operation, *(arguments or [])])
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", program, parameters, None, 1)
        return int(result) > 32
    # Linux is expected to use a package-installed pkexec policy/launcher.
    helper = shutil.which("pkexec")
    if helper:
        try:
            subprocess.Popen([helper, str(Path(sys.argv[0]).resolve()), "--elevated"])
            return True
        except OSError:
            pass
    return False
