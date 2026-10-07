from __future__ import annotations

import ctypes
import os
from pathlib import Path

from weave_cli.platforms.base import BasePlatform


class WindowsPlatform(BasePlatform):
    """
    Windows-specific platform implementation for the WEAVE CBT CLI.
    """

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
