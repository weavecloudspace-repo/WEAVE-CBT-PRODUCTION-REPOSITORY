"""Read-only WEAVE CBT installation and container status."""

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, fail, get_stack, info, success, warning,
)


def status() -> None:
    """Show the installed version, Docker runtime and running containers."""
    banner("System status")
    try:
        stack = get_stack()
        info(f"Installed version: {stack.installation.installed_version}")
        info(f"Runtime: {stack.installation.runtime_type}")

        if not stack.runtime.docker_engine_running():
            warning("Docker Engine is not running.")
            raise typer.Exit(code=1)
        success("Docker Engine is running.")

        if not stack.runtime.docker_compose_available():
            warning("Docker Compose is unavailable.")
            raise typer.Exit(code=1)
        success("Docker Compose is available.")

        result = stack.compose.status()
        typer.echo("\nContainers:")
        typer.echo(result.stdout or "No running containers.")
        if not result.stdout.strip():
            raise typer.Exit(code=1)

    except COMMAND_ERRORS as exc:
        fail(exc)


def register(app: typer.Typer) -> None:
    app.command(name="status")(status)
