from __future__ import annotations

from pathlib import Path

from .runtime import (
    DEFAULT_TIMEOUT,
    CommandResult,
    DockerRuntime,
)


class DockerComposeError(RuntimeError):
    """Raised when an error occurs while interacting with Docker Compose."""


class DockerCompose:
    """
    Manages the WEAVE CBT Docker Compose stack.
    """

    def __init__(
        self,
        *,
        compose_file: Path,
        env_file: Path,
        project_name: str = "weave-cbt",
    ) -> None:
        self.compose_file = compose_file
        self.env_file = env_file
        self.project_name = project_name

    def _run_compose_command(
        self,
        command: list[str],
        *,
        stream: bool = False,
        timeout: int | None = DEFAULT_TIMEOUT,
    ) -> CommandResult:
        """
        Runs a Docker Compose command with the specified arguments
        and invokes the DockerRuntime to execute the command.
        """

        if not self.compose_file.is_file():
            raise DockerComposeError(
                f"Compose file '{self.compose_file}' does not exist."
            )

        if not self.env_file.is_file():
            raise DockerComposeError(
                f"Environment file '{self.env_file}' does not exist."
            )

        result = DockerRuntime.run_docker_command(
            arguments=[
                "compose",
                "-f",
                str(self.compose_file),
                "--env-file",
                str(self.env_file),
                "-p",
                self.project_name,
            ]
            + command,
            stream=stream,
            timeout=None if stream else timeout,
        )

        if not result.successful:
            raise DockerComposeError(
                f"Failed to execute the Compose command (exit {result.return_code}): "
                f"{result.stderr or 'See terminal output for details.'}"
            )

        return result

    def start(
        self,
    ) -> CommandResult:
        """
        Start the WEAVE CBT Compose stack in detached mode.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            up -d
        """

        return self._run_compose_command(command=["up", "-d"], timeout=None)

    def stop(
        self,
    ) -> CommandResult:
        """
        Stop the WEAVE CBT Compose stack.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            down
        """

        return self._run_compose_command(command=["down"], timeout=None)

    def restart(
        self,
    ) -> CommandResult:
        """
        Restart the WEAVE CBT Compose stack.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            restart
        """

        return self._run_compose_command(command=["restart"], timeout=None)

    def status(
        self,
    ) -> CommandResult:
        """
        Show the status of the WEAVE CBT Compose stack.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            ps
        """

        return self._run_compose_command(command=["ps"])

    def pull_weave_image(
        self,
    ) -> CommandResult:
        """
        Pull the WEAVE CBT application image used by the bootstrap,
        API, and worker services.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            pull bootstrap api worker
        """

        return self._run_compose_command(
            command=["pull", "bootstrap", "api", "worker"],
            timeout=None,
        )

    def pull_postgres_image(
        self,
    ) -> CommandResult:
        """
        Pull the PostgreSQL image used by the WEAVE CBT stack.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            pull postgres
        """

        return self._run_compose_command(
            command=["pull", "postgres"],
            timeout=None,
        )

    def pull_redis_image(
        self,
    ) -> CommandResult:
        """
        Pull the Redis image used by the WEAVE CBT stack.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            pull redis
        """

        return self._run_compose_command(
            command=["pull", "redis"],
            timeout=None,
        )

    def pull_nginx_image(
        self,
    ) -> CommandResult:
        """
        Pull the Nginx image used by the WEAVE CBT stack.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            pull nginx
        """

        return self._run_compose_command(
            command=["pull", "nginx"],
            timeout=None,
        )

    def logs(
        self,
        service: str | None = None,
        follow: bool = False,
    ) -> CommandResult:
        """
        Show the logs of the WEAVE CBT Compose stack.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            logs
        """

        command = ["logs"]

        if follow:
            command.append("-f")

        if service:
            command.append(service)

        return self._run_compose_command(
            command=command,
            stream=follow,
        )

    def config(
        self,
    ) -> CommandResult:
        """
        Validate the WEAVE CBT Compose configuration without printing
        resolved values.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            config --quiet
        """

        return self._run_compose_command(command=["config", "--quiet"])

    def destroy(
        self,
    ) -> CommandResult:
        """
        Stop the WEAVE CBT Compose stack and remove its containers,
        project networks, volumes, and orphaned containers.

        Equivalent to:

        docker compose \
            -f <compose_file> \
            --env-file <env_file> \
            -p <project_name> \
            down --volumes --remove-orphans
        """

        return self._run_compose_command(
            command=["down", "--volumes", "--remove-orphans"],
            timeout=None,
        )
