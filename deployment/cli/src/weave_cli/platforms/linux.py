from __future__ import annotations

import os
from pathlib import Path

from weave_cli.platforms.base import BasePlatform


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
