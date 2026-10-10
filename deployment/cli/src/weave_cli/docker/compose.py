from __future__ import annotations

import re
import time
from pathlib import Path

from weave_cli.docker.runtime import (
    DEFAULT_TIMEOUT,
    CommandResult,
    DockerRuntime,
    DockerRuntimeError,
)



_POSTGRES_ENV_GUARD = """
# The database name comes from the installed, admin-controlled Postgres config.
# Reject punctuation before quoting SQL identifiers.
case "${POSTGRES_DB:-}" in
  "") echo "PostgreSQL container is missing POSTGRES_DB; refusing snapshot." >&2; exit 64 ;;
  *[!A-Za-z0-9_]*) echo "Unsafe PostgreSQL database name in container configuration." >&2; exit 64 ;;
esac
case "${POSTGRES_USER:-}" in
  "") echo "Missing PostgreSQL user" >&2; exit 64 ;;
esac
"""

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
        runtime: DockerRuntime,
        project_name: str = "weave-cbt",
    ) -> None:
        self.compose_file = compose_file
        self.env_file = env_file
        self.runtime = runtime
        self.project_name = project_name

    def _run_compose_command(
        self,
        command: list[str],
        *,
        stream: bool = False,
        timeout: int | None = DEFAULT_TIMEOUT,
        stall_timeout: int | None = None,
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

        compose_path = self.runtime.translate_path(self.compose_file)
        env_path = self.runtime.translate_path(self.env_file)

        result = self.runtime.run_docker_command(
            arguments=[
                "compose",
                "-f",
                compose_path,
                "--env-file",
                env_path,
                "-p",
                self.project_name,
            ]
            + (
                ["--profile", "tls"]
                if (self.env_file.parent / "tls.enabled").exists()
                else []
            )
            + command,
            stream=stream,
            timeout=None if stream and timeout == DEFAULT_TIMEOUT else timeout,
            stall_timeout=stall_timeout,
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

    def stop_application(self) -> CommandResult:
        """Quiesce all application writers while retaining PostgreSQL and Redis."""
        return self._run_compose_command(
            command=["stop", "nginx", "api", "worker", "bootstrap"],
            timeout=None,
        )

    @staticmethod
    def _validate_snapshot_name(name: str) -> str:
        """Accept only CLI-generated identifiers; never interpolate arbitrary SQL."""
        if not re.fullmatch(r"weave_cbt_(?:rollback|failed)_[0-9a-f]{32}", name):
            raise ValueError("Invalid WEAVE CBT rollback database identifier.")
        return name

    def _postgres_maintenance(self, script: str, *arguments: str) -> CommandResult:
        """Run PostgreSQL maintenance through the configured Linux/WSL provider."""
        return self._run_compose_command(
            command=[
                "exec", "-T", "postgres", "sh", "-eu", "-c",
                script, "weave-cbt-db", *arguments,
            ],
            timeout=None,
        )

    def verify_database_maintenance(self) -> CommandResult:
        """Read-only maintenance preflight while exam services still run.

        Ensure the target Postgres container has its expected environment,
        and that the maintenance database accepts connections, BEFORE we
        stop the application's writers or create an update-recovery journal.
        """
        return self._postgres_maintenance(
            _POSTGRES_ENV_GUARD
            + """
psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -Atqc 'SELECT 1' >/dev/null
"""
        )

    def snapshot_database(self, backup_name: str) -> CommandResult:
        """Snapshot the entire local database before applying the new image."""
        self._validate_snapshot_name(backup_name)
        return self._postgres_maintenance(
            _POSTGRES_ENV_GUARD
            + """
test "$POSTGRES_DB" != postgres || {
  echo "Cannot snapshot the maintenance database." >&2; exit 1;
}
psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \\
  -c "CREATE DATABASE \\"$1\\" WITH TEMPLATE \\"$POSTGRES_DB\\""
""",
            backup_name,
        )

    def restore_database(self, backup_name: str, failed_name: str) -> CommandResult:
        """Swap the saved database into place. Preserve the failed version."""
        self._validate_snapshot_name(backup_name)
        self._validate_snapshot_name(failed_name)
        return self._postgres_maintenance(
            _POSTGRES_ENV_GUARD
            + """
test "$POSTGRES_DB" != postgres || exit 1
psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \\
  -c "ALTER DATABASE \\"$POSTGRES_DB\\" RENAME TO \\"$2\\""
if ! psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \\
  -c "ALTER DATABASE \\"$1\\" RENAME TO \\"$POSTGRES_DB\\""; then
  # Try to restore the original name if the snapshot could not be activated.
  psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \\
    -c "ALTER DATABASE \\"$2\\" RENAME TO \\"$POSTGRES_DB\\"" || true
  exit 1
fi
""",
            backup_name, failed_name,
        )

    def drop_snapshot_database(self, database_name: str) -> CommandResult:
        """Delete a no-longer-needed snapshot, never the configured live DB."""
        self._validate_snapshot_name(database_name)
        return self._postgres_maintenance(
            _POSTGRES_ENV_GUARD
            + """
psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \\
  -c "DROP DATABASE IF EXISTS \\"$1\\""
""",
            database_name,
        )

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

    def _pull_with_retry(self, services: list[str]) -> CommandResult:
        """Show pull progress and retry bounded network failures.

        A failed pull does not delete cached image layers. Subsequent attempts
        reuse Docker's completed downloads. This does not interrupt dpkg or
        any application/database state.
        """
        failures: list[str] = []
        for attempt in range(1, 4):
            print(f"[WEAVE][ACTION] Pulling {', '.join(services)} (attempt {attempt}/3)", flush=True)
            try:
                return self._run_compose_command(
                    command=["pull", *services],
                    stream=True,
                    timeout=1200,
                    stall_timeout=180,
                )
            except (DockerComposeError, DockerRuntimeError) as exc:
                failures.append(str(exc))
                if attempt < 3:
                    print(f"[WEAVE][WARN] Docker image pull failed; retrying in {5 * attempt}s: {exc}", flush=True)
                    time.sleep(5 * attempt)
        raise DockerComposeError(
            f"Docker image pull failed after three attempts for {', '.join(services)}: {failures[-1]}"
        )

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

        return self._pull_with_retry(["bootstrap", "api", "worker"])

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

        return self._pull_with_retry(["postgres"])

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

        return self._pull_with_retry(["redis"])

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

        return self._pull_with_retry(["nginx"])

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
