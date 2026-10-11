"""Read live Compose output or human-readable CBT error archives."""
from __future__ import annotations

from datetime import date
import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, SERVICES, banner, error, fail, get_stack, info, success,
)
from weave_cli.commands.error_archive import get_error_records


def logs(
    service: str | None = typer.Argument(
        None, help="Optional service: api, worker, postgres, redis, nginx, bootstrap."
    ),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow live Compose logs."),
    errors: bool = typer.Option(False, "--errors", help="Read persistent error reports."),
    day: str | None = typer.Option(None, "--date", help="Archive date YYYY-MM-DD (with --errors)."),
    last: int = typer.Option(20, "--last", min=1, max=100, help="Maximum archived errors."),
) -> None:
    """Inspect service logs without changing any container state."""
    if service is not None and service not in SERVICES:
        error(f"Unknown service '{service}'. Choose from: {', '.join(SERVICES)}")
        raise typer.Exit(code=2)
    if errors and follow:
        error("--errors and --follow cannot be combined.")
        raise typer.Exit(code=2)
    if not errors and (day is not None or last != 20):
        error("--date/--last require --errors.")
        raise typer.Exit(code=2)
    if day is not None:
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError
        except ValueError:
            error("Date must use YYYY-MM-DD.")
            raise typer.Exit(code=2)

    banner(f"{'Archived errors' if errors else 'Logs'} · {service or 'all services'}")
    try:
        stack = get_stack()
        if errors:
            reports = get_error_records(stack.installation.data_directory,
                                        service=service, day=day, limit=last)
            if service in {"postgres", "redis", "nginx"} and not reports:
                info("This service retains rotated Docker logs, not formatted host error reports.")
                info(f"Use 'weave logs {service}' to inspect its live/retained output.")
            typer.echo("\n\n".join(reports) if reports else "No archived application errors found.")
            return
        info("Press Ctrl+C to stop following." if follow else "Retrieving logs...")
        result = stack.compose.logs(service=service, follow=follow)
        if follow:
            success("Stopped following logs.")
        else:
            typer.echo(result.stdout or "No logs available.")
            if result.stderr:
                typer.echo(result.stderr, err=True)
    except (*COMMAND_ERRORS, ValueError) as exc:
        fail(exc)
    except KeyboardInterrupt:
        success("Stopped following logs.")


def register(app: typer.Typer) -> None:
    app.command(name="logs")(logs)
