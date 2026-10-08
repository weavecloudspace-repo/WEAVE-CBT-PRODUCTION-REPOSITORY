from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PlatformError(RuntimeError):
    """Raised when a platform-specific operation cannot be completed."""


class BasePlatform(ABC):
    """
    Defines the common platform contract used by the WEAVE CBT CLI.

    Platform-specific implementations provide sensible default paths,
    the canonical location of the installation state file, and host
    runtime operations.
    """

    @property
    @abstractmethod
    def default_install_directory(self) -> Path:
        """
        Return the platform's default directory for installed WEAVE CBT
        program and deployment files.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def default_data_directory(self) -> Path:
        """
        Return the platform's default directory for mutable WEAVE CBT
        runtime data and configuration.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def installation_state_path(self) -> Path:
        """
        Return the canonical path to the WEAVE CBT installation state file.

        This file records the actual installation location selected during
        setup and must live at a predictable platform-specific location.
        """
        raise NotImplementedError

    @abstractmethod
    def is_admin(self) -> bool:
        """
        Return True when the current process has elevated system privileges.
        """
        raise NotImplementedError

    @abstractmethod
    def start_docker_engine(self) -> None:
        """
        Start the Docker Engine managed by the current platform.

        Raise PlatformError when the engine cannot be started.
        """
        raise NotImplementedError
