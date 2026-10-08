from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from weave_cli.docker.provider import (
    DockerCommandProvider,
    DockerProviderError,
)

DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str

    @property
    def successful(self) -> bool:
        return self.return_code == 0


class DockerRuntimeError(RuntimeError):
    """Raised when a Docker runtime operation cannot be completed."""


class DockerRuntime:
    """
    Execute Docker commands through a supplied Docker command provider.

    The runtime owns subprocess execution, output capture, timeouts, and
    process cleanup. The provider owns how Docker is reached on the host.
    """

    def __init__(self, provider: DockerCommandProvider) -> None:
        self.provider = provider

    def translate_path(self, path: Path) -> str:
        """Translate a host path into the path visible to Docker."""
        try:
            return self.provider.translate_path(path)
        except DockerProviderError as exc:
            raise DockerRuntimeError(str(exc)) from exc

    def run_docker_command(
        self,
        arguments: Sequence[str],
        *,
        timeout: int | None = DEFAULT_TIMEOUT,
        stream: bool = False,
    ) -> CommandResult:
        """
        Execute a Docker CLI command through the configured provider.

        With stream=True, output goes directly to the terminal and the
        returned output strings are empty. Pass timeout=None for commands
        that should not have an execution timeout.
        """

        if isinstance(arguments, str):
            raise TypeError(
                "Docker command arguments must be a sequence of strings, "
                "not a single string."
            )

        try:
            process_command = self.provider.build_command(arguments)
        except DockerProviderError as exc:
            raise DockerRuntimeError(str(exc)) from exc

        try:
            with ExitStack() as stack:
                stdout = (
                    None if stream else stack.enter_context(tempfile.TemporaryFile())
                )
                stderr = (
                    None if stream else stack.enter_context(tempfile.TemporaryFile())
                )
                process = subprocess.Popen(
                    process_command,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=os.name != "nt",
                )
                try:
                    return_code = process.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    self._stop_process_tree(process)
                    raise

                return CommandResult(
                    return_code=return_code,
                    stdout="" if stdout is None else self._read_output(stdout),
                    stderr="" if stderr is None else self._read_output(stderr),
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
        """Stop the command and its child processes, then reap the launcher."""
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

    def docker_cli_available(self) -> bool:
        """Return True when the provider can reach a Docker CLI."""

        try:
            result = self.run_docker_command(["--version"])
        except DockerRuntimeError:
            return False

        return result.successful

    def docker_engine_running(self) -> bool:
        """Return True when Docker Engine is running and reachable."""

        try:
            result = self.run_docker_command(["info"])
        except DockerRuntimeError:
            return False

        return result.successful

    def docker_compose_available(self) -> bool:
        """Return True when the Docker Compose plugin is available."""

        try:
            result = self.run_docker_command(["compose", "version"])
        except DockerRuntimeError:
            return False

        return result.successful

    def get_docker_version(self) -> str:
        """Return the Docker CLI version exposed by the provider."""

        result = self.run_docker_command(["--version"])

        if not result.successful:
            raise DockerRuntimeError(f"Failed to get Docker version: {result.stderr}")

        return result.stdout

    def get_compose_version(self) -> str:
        """Return the Docker Compose version exposed by the provider."""

        result = self.run_docker_command(["compose", "version"])

        if not result.successful:
            raise DockerRuntimeError(
                f"Failed to get Docker Compose version: {result.stderr}"
            )

        return result.stdout
