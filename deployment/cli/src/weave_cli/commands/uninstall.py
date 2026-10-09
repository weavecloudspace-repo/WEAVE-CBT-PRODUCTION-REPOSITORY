"""Unregister the installation and remove Compose containers safely."""

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, error, get_stack, info, success, warning,
)


def uninstall(
    purge_volumes: bool = typer.Option(
        False, "--purge-volumes", help="Permanently delete WEAVE CBT Docker volumes."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the first confirmation."),
) -> None:
    """Remove application containers; preserve school data by default."""
    banner("Uninstall WEAVE CBT")
    try:
        stack = get_stack()
        if not stack.platform.is_admin():
            raise PermissionError("Administrative privileges are required.")

        if not yes and not typer.confirm("Uninstall WEAVE CBT?", default=False):
            warning("Uninstall cancelled.")
            return

        if purge_volumes:
            warning("PostgreSQL and application Docker volumes will be deleted permanently.")
            if typer.prompt("Type DELETE DATA to confirm") != "DELETE DATA":
                warning("Data deletion cancelled.")
                return

        info("Removing application containers...")
        if purge_volumes:
            stack.compose.destroy()
        else:
            stack.compose.stop()

        # Registration is deleted only after Compose succeeds. Do not erase
        # runtime.env, data directories, distro, or unrelated Docker resources.
        stack.manager.delete()
        success("WEAVE CBT unregistered; application files were retained.")
        if purge_volumes:
            warning("Compose-managed volumes were removed.")
        else:
            success("Persistent school data volumes were preserved.")
        info("Docker Engine and WSL were not removed.")
    except (*COMMAND_ERRORS, PermissionError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="uninstall")(uninstall)
