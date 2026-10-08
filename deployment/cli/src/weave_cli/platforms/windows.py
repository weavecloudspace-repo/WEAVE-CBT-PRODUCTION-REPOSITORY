from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from pathlib import Path

from weave_cli.platforms.base import BasePlatform, PlatformError


class WindowsPlatform(BasePlatform):
    """
    Windows-specific platform implementation for the WEAVE CBT CLI.
    """

    def __init__(self, wsl_distribution: str = "Ubuntu") -> None:
        self.wsl_distribution = wsl_distribution

    @property
    def default_install_directory(self) -> Path:
        """
        Return the default Windows installation directory.

        Default:
            C:\\Program Files\\WeaveCBT
        """

        program_files = os.environ.get("ProgramFiles")

        if not program_files:
            program_files = r"C:\Program Files"

        return Path(program_files) / "WeaveCBT"

    @property
    def default_data_directory(self) -> Path:
        """
        Return the default Windows data directory.

        Default:
            C:\\ProgramData\\WeaveCBT
        """

        program_data = os.environ.get("ProgramData")

        if not program_data:
            program_data = r"C:\ProgramData"

        return Path(program_data) / "WeaveCBT"

    @property
    def installation_state_path(self) -> Path:
        """
        Return the canonical path to the WEAVE CBT installation state file.

        Default:
            C:\\ProgramData\\WeaveCBT\\install.json
        """

        return self.default_data_directory / "install.json"

    def is_admin(self) -> bool:
        """
        Return True when the current Windows process is running
        with Administrator privileges.
        """

        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def start_docker_engine(self) -> None:
        """
        Start Docker Engine inside the WEAVE WSL distribution.

        Docker Engine must already be installed in the configured WSL
        distribution by the WEAVE bootstrap process.
        """

        wsl_executable = shutil.which("wsl.exe") or shutil.which("wsl")

        if wsl_executable is None:
            raise PlatformError("WSL is not installed or is not available in PATH.")

        command = [
            wsl_executable,
            "--distribution",
            self.wsl_distribution,
            "--user",
            "root",
            "--",
            "systemctl",
            "start",
            "docker",
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PlatformError(
                "Timed out while starting Docker Engine inside WSL."
            ) from exc
        except OSError as exc:
            raise PlatformError(
                f"Failed to start Docker Engine inside WSL: {exc}"
            ) from exc

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            raise PlatformError(
                "Failed to start Docker Engine inside "
                f"WSL distribution '{self.wsl_distribution}': "
                f"{error or 'unknown error'}"
            )
