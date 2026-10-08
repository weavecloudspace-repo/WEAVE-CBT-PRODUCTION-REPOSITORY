from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path, PureWindowsPath

WEAVE_WSL_DISTRIBUTION = "WeaveCBT"


class DockerProviderError(RuntimeError):
    """Raised when a Docker command provider cannot prepare a command."""


class DockerCommandProvider(ABC):
    """
    Defines how Docker commands are reached on a specific host runtime.

    Providers are responsible for building the actual process command and
    translating host filesystem paths into paths visible to that runtime.
    """

    @abstractmethod
    def build_command(self, arguments: Sequence[str]) -> list[str]:
        """Build the executable command used to invoke Docker."""
        raise NotImplementedError

    @abstractmethod
    def translate_path(self, path: Path) -> str:
        """Translate a host path into the path visible to Docker."""
        raise NotImplementedError


class LinuxDockerProvider(DockerCommandProvider):
    """Use the Docker CLI installed directly on the Linux host."""

    def build_command(self, arguments: Sequence[str]) -> list[str]:
        docker_executable = shutil.which("docker")

        if docker_executable is None:
            raise DockerProviderError(
                "Docker CLI is not installed or is not found in the system PATH."
            )

        return [docker_executable, *arguments]

    def translate_path(self, path: Path) -> str:
        return str(path)


class WindowsWslDockerProvider(DockerCommandProvider):
    """
    Run Docker inside WEAVE's dedicated WSL distribution.

    The WEAVE Windows runtime is intentionally fixed to the WeaveCBT WSL
    distribution so host Docker Desktop contexts are never used accidentally.
    """

    def build_command(self, arguments: Sequence[str]) -> list[str]:
        wsl_executable = shutil.which("wsl.exe") or shutil.which("wsl")

        if wsl_executable is None:
            raise DockerProviderError(
                "WSL is not installed or is not found in the system PATH."
            )

        return [
            wsl_executable,
            "--distribution",
            WEAVE_WSL_DISTRIBUTION,
            "--user",
            "root",
            "--",
            "docker",
            *arguments,
        ]

    def translate_path(self, path: Path) -> str:
        """
        Convert a Windows host path to the path exposed inside WSL.

        Example:
            C:\\Program Files\\WeaveCBT\\compose.yaml
            -> /mnt/c/Program Files/WeaveCBT/compose.yaml
        """

        windows_path = PureWindowsPath(str(path))
        drive = windows_path.drive

        if len(drive) != 2 or drive[1] != ":":
            raise DockerProviderError(
                f"Windows path '{path}' must use a local drive such as C:\\."
            )

        relative_parts = windows_path.relative_to(windows_path.anchor).parts
        mount_root = f"/mnt/{drive[0].lower()}"

        if not relative_parts:
            return mount_root

        return f"{mount_root}/{'/'.join(relative_parts)}"
