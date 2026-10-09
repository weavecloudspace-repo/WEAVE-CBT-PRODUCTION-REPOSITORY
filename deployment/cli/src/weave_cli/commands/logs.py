"""View or follow Docker Compose logs for installed WEAVE CBT services."""

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, SERVICES, banner, error, fail, get_stack, info,
)


def logs(
    service: str | None = typer.Argument(
        None, help="Optional service: api, worker, postgres, redis, nginx, bootstrap."
    ),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow live logs."),
) -> None:
    """Read WEAVE CBT service logs."""
    if service is not None and service not in SERVICES:
        error(f"Unknown service '{service}'. Choose from: {', '.join(SERVICES)}")
        raise typer.Exit(code=2)

    banner(f"Logs · {service or 'all services'}")
    try:
        stack = get_stack()
        info("Press Ctrl+C to stop following." if follow else "Retrieving logs...")
        result = stack.compose.logs(service=service, follow=follow)
        if not follow:
            typer.echo(result.stdout or "No logs available.")
            if result.stderr:
                typer.echo(result.stderr, err=True)
    except COMMAND_ERRORS as exc:
        fail(exc)
    except KeyboardInterrupt:
        typer.echo()


def register(app: typer.Typer) -> None:
    app.command(name="logs")(logs)
