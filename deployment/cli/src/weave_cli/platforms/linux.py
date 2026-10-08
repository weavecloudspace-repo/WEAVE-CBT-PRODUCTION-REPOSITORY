from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from weave_cli.platforms.base import BasePlatform, PlatformError


class LinuxPlatform(BasePlatform):
    """
    Linux-specific platform implementation for the WEAVE CBT CLI.
    """

    @property
    def default_install_directory(self) -> Path:
        """
        Return the default Linux installation directory.

        Default:
            /opt/weave-cbt
        """

        return Path("/opt/weave-cbt")

    @property
    def default_data_directory(self) -> Path:
        """
        Return the default Linux data directory.

        Default:
            /var/lib/weave-cbt
        """

        return Path("/var/lib/weave-cbt")

    @property
    def installation_state_path(self) -> Path:
        """
        Return the canonical path to the WEAVE CBT installation state file.

        Default:
            /var/lib/weave-cbt/install.json
        """

        return self.default_data_directory / "install.json"

    def is_admin(self) -> bool:
        """
        Return True when the current Linux process is running
        with root privileges.
        """

        geteuid = getattr(os, "geteuid", None)

        if geteuid is None:
            return False

        return geteuid() == 0

    def start_docker_engine(self) -> None:
        """
        Start Docker Engine using the Linux systemd service manager.
        """

        systemctl_executable = shutil.which("systemctl")

        if systemctl_executable is None:
            raise PlatformError("systemctl is not installed or is not available in PATH.")

        try:
            result = subprocess.run(
                [systemctl_executable, "start", "docker"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PlatformError("Timed out while starting Docker Engine.") from exc
        except OSError as exc:
            raise PlatformError(f"Failed to start Docker Engine: {exc}") from exc

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            raise PlatformError(
                f"Failed to start Docker Engine: {error or 'unknown error'}"
            )
