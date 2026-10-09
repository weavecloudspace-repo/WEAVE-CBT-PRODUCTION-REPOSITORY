"""Read-only operational diagnostics for a WEAVE CBT installation."""

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, error, get_stack, info, success, warning,
)


def doctor() -> None:
    """Check installation state, Docker, Compose and container availability."""
    banner("System diagnostics")
    try:
        stack = get_stack()
        success("Installation state and deployment files are valid.")

        for available, description in (
            (stack.runtime.docker_cli_available(), "Docker CLI"),
            (stack.runtime.docker_engine_running(), "Docker Engine"),
            (stack.runtime.docker_compose_available(), "Compose plugin"),
        ):
            if not available:
                error(f"{description} is unavailable.")
                raise typer.Exit(code=1)
            success(f"{description} is available.")

        stack.compose.config()
        success("Compose configuration is valid.")

        result = stack.compose.status()
        info("Running containers:")
        typer.echo(result.stdout or "None")
        if not result.stdout.strip():
            warning("No running containers detected.")
            raise typer.Exit(code=1)

        success("Basic diagnostics complete. Check container health separately.")
    except COMMAND_ERRORS as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="doctor")(doctor)
