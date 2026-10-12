"""Shared console presentation and installed-stack dependency wiring."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import typer
from colorama import Fore, Style, just_fix_windows_console

from weave_cli.docker.compose import DockerCompose, DockerComposeError
from weave_cli.docker.provider import LinuxDockerProvider, WindowsWslDockerProvider
from weave_cli.docker.runtime import DockerRuntime, DockerRuntimeError
from weave_cli.installation import (
    InstallationManager,
    InstallationState,
    InstallationStateError,
)
from weave_cli.platforms.base import BasePlatform, PlatformError
from weave_cli.platforms.linux import LinuxPlatform
from weave_cli.platforms.windows import WindowsPlatform

just_fix_windows_console()

BLUE = Fore.LIGHTBLUE_EX
GREEN = Fore.LIGHTGREEN_EX
YELLOW = Fore.LIGHTYELLOW_EX
RED = Fore.LIGHTRED_EX
CYAN = Fore.CYAN
WHITE = Fore.WHITE
RESET = Style.RESET_ALL

SERVICES = ("api", "worker", "postgres", "redis", "nginx", "bootstrap")
COMMAND_ERRORS = (
    InstallationStateError,
    DockerComposeError,
    DockerRuntimeError,
    PlatformError,
    OSError,
)


def _paint(message: str, color: str) -> str:
    return f"{color}{message}{RESET}"


def banner(title: str) -> None:
    typer.echo()
    typer.echo(_paint("◆ WEAVE CBT", BLUE + Style.BRIGHT) + "  " + _paint(title, WHITE))
    typer.echo(_paint("─" * 45, BLUE))


def success(message: str) -> None:
    typer.echo(_paint(f"✓ {message}", GREEN))


def info(message: str) -> None:
    typer.echo(_paint(f"› {message}", CYAN))


def warning(message: str) -> None:
    typer.echo(_paint(f"! {message}", YELLOW))


def error(message: str) -> None:
    typer.echo(_paint(f"✗ {message}", RED), err=True)


def fail(exc: Exception) -> None:
    error(str(exc))
    raise typer.Exit(code=1) from exc


@dataclass(frozen=True)
class Stack:
    platform: BasePlatform
    manager: InstallationManager
    installation: InstallationState
    runtime: DockerRuntime
    compose: DockerCompose


def get_stack() -> Stack:
    """Load persisted locations; never guess where a school was installed."""
    if sys.platform == "win32":
        platform = WindowsPlatform(wsl_distribution="WeaveCBT")
        provider = WindowsWslDockerProvider()
    elif sys.platform.startswith("linux"):
        platform = LinuxPlatform()
        provider = LinuxDockerProvider()
    else:
        raise PlatformError("WEAVE CBT supports Windows and Linux only.")

    manager = InstallationManager(platform)
    installation = manager.load()
    runtime = DockerRuntime(provider)
    return Stack(
        platform=platform,
        manager=manager,
        installation=installation,
        runtime=runtime,
        compose=DockerCompose(
            compose_file=installation.install_directory / "compose.yaml",
            env_file=installation.data_directory / "runtime.env",
            runtime=runtime,
        ),
    )


def save_runtime_env(path: Path, content: bytes) -> None:
    """Write a private runtime.env atomically, retaining Windows ACL protection."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".runtime-", suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            if os.name != "nt":
                os.chmod(temporary, stat.S_IMODE(path.stat().st_mode) & 0o600)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        if os.name == "nt":
            result = subprocess.run(
                [
                    "icacls", str(temporary), "/inheritance:r",
                    "/grant:r", "*S-1-5-18:F", "*S-1-5-32-544:F",
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if result.returncode != 0:
                raise OSError("Failed to secure temporary runtime configuration.")

        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
