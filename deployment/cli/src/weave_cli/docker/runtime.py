from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from typing import BinaryIO

DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str  # standard output
    stderr: str  # standard error

    @property
    def successful(self) -> bool:
        return self.return_code == 0


class DockerRuntimeError(RuntimeError):
    """Raised when a Docker runtime operation cannot be completed."""


class DockerRuntime:
    """
    This class provides methods for interacting with Docker CLI commands.

    It is OS-independent and can be used on any platform where the
    Docker CLI is installed and available in the system PATH.
    """

    @staticmethod
    def run_docker_command(
        arguments: Sequence[str],
        *,
        timeout: int | None = DEFAULT_TIMEOUT,
        stream: bool = False,
    ) -> CommandResult:
        """
        Execute a Docker CLI command.

        With stream=True, output goes directly to the terminal and the
        returned output strings are empty. Pass timeout=None for commands
        that should not have an execution timeout.

        Example:
            run_docker_command(["compose", "ps"])

        Executes:
            docker compose ps
        """

        if isinstance(arguments, str):
            raise TypeError(
                "Docker command arguments must be a sequence of strings, "
                "not a single string."
            )

        docker_executable = shutil.which("docker")

        if docker_executable is None:
            raise DockerRuntimeError(
                "Docker CLI is not installed or is not found in the system PATH."
            )

        try:
            with ExitStack() as stack:
                # Compose launches a plugin process. Files avoid waiting for
                # inherited output pipes to close after the launcher exits.
                stdout = (
                    None if stream else stack.enter_context(tempfile.TemporaryFile())
                )
                stderr = (
                    None if stream else stack.enter_context(tempfile.TemporaryFile())
                )
                process = subprocess.Popen(
                    [docker_executable, *arguments],
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=os.name != "nt",
                )
                try:
                    return_code = process.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    DockerRuntime._stop_process_tree(process)
                    raise

                return CommandResult(
                    return_code=return_code,
                    stdout="" if stdout is None else DockerRuntime._read_output(stdout),
                    stderr="" if stderr is None else DockerRuntime._read_output(stderr),
                )

        except subprocess.TimeoutExpired as exc:
            raise DockerRuntimeError(
                f"Docker command timed out after {timeout} seconds."
            ) from exc

        except OSError as exc:
            raise DockerRuntimeError(
                f"Failed to execute Docker command: {exc}"
            ) from exc

    @staticmethod
    def _read_output(output: BinaryIO) -> str:
        output.seek(0)
        return output.read().decode("utf-8", errors="replace").strip()

    @staticmethod
    def _stop_process_tree(process: subprocess.Popen) -> None:
        """Stop the command and its plugin processes, then reap the launcher."""
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def docker_cli_available() -> bool:
        """Return True when the Docker CLI is available."""

        if shutil.which("docker") is None:
            return False

        try:
            result = DockerRuntime.run_docker_command(["--version"])
        except DockerRuntimeError:
            return False

        return result.successful

    @staticmethod
    def docker_engine_running() -> bool:
        """Return True when the Docker Engine is running and reachable."""

        try:
            result = DockerRuntime.run_docker_command(["info"])
        except DockerRuntimeError:
            return False

        return result.successful

    @staticmethod
    def docker_compose_available() -> bool:
        """Return True when the Docker Compose plugin is available."""

        try:
            result = DockerRuntime.run_docker_command(["compose", "version"])
        except DockerRuntimeError:
            return False

        return result.successful

    @staticmethod
    def get_docker_version() -> str:
        """Return the version of the Docker CLI installed on the system."""

        result = DockerRuntime.run_docker_command(["--version"])

        if not result.successful:
            raise DockerRuntimeError(f"Failed to get Docker version: {result.stderr}")

        return result.stdout

    @staticmethod
    def get_compose_version() -> str:
        """Return the installed Docker Compose version."""

        result = DockerRuntime.run_docker_command(["compose", "version"])

        if not result.successful:
            raise DockerRuntimeError(
                f"Failed to get Docker Compose version: {result.stderr}"
            )

        return result.stdout
