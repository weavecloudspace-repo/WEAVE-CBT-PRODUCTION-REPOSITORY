"""Stop the Compose stack without removing named volumes."""

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, fail, get_stack, info, success,
)


def stop() -> None:
    """Stop WEAVE CBT containers without deleting school data."""
    banner("Stopping services")
    try:
        stack = get_stack()
        info("Stopping application containers...")
        stack.compose.stop()
        success("WEAVE CBT stopped; persistent Docker volumes preserved.")
    except COMMAND_ERRORS as exc:
        fail(exc)


def register(app: typer.Typer) -> None:
    app.command(name="stop")(stop)
