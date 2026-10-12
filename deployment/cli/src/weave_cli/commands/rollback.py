"""Recover an interrupted CBT update or revert the last image and DB together."""

from __future__ import annotations

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS,
    banner,
    error,
    get_stack,
    success,
    warning,
)
from weave_cli.commands.update import restore_previous
from weave_cli.commands.update_recovery import (
    read_recovery,
    recovery_path,
    update_lock,
)


def rollback() -> None:
    """Restore the previous image and exact pre-update database snapshot."""
    banner("Rolling back WEAVE CBT")
    try:
        stack = get_stack()
        if not stack.platform.is_admin():
            raise PermissionError("Administrative privileges are required for rollback.")
        if not stack.runtime.docker_engine_running():
            raise RuntimeError("Docker Engine is not running.")
        data_dir = stack.installation.data_directory
        with update_lock(data_dir):
            record = read_recovery(recovery_path(data_dir))
            if record is None:
                raise RuntimeError("No image/database restore point is available.")

            warning(
                "Rollback restores the database to its pre-update snapshot. "
                "ALL exam attempts, results and other changes written since "
                "that snapshot will be LOST."
            )
            if not typer.confirm(
                f"Restore image {record.previous_image} and its saved database?",
                default=False,
            ):
                warning("Rollback cancelled.")
                return
            restore_previous(stack, record)
        success("Previous image and database restored and verified.")
    except (*COMMAND_ERRORS, ValueError, RuntimeError, PermissionError) as exc:
        error(
            str(exc)
            + " Recovery state is retained if rollback did not complete."
        )
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="rollback")(rollback)
