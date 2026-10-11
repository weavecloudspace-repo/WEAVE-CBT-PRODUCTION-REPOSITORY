"""Unregister the installation and remove Compose containers safely."""

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, error, get_stack, info, success, warning,
)

from weave_cli.commands.lan import configure, LanError, _state_path
from weave_cli.commands.purge_safety import PurgeSafetyError, verify_purged_resources


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
            warning("PostgreSQL, CBT identity and TLS certificate Docker volumes will be deleted permanently.")
            if typer.prompt("Type DELETE DATA to confirm") != "DELETE DATA":
                warning("Data deletion cancelled.")
                return

        info("Removing application containers...")
        if purge_volumes:
            stack.compose.destroy()
            # Compose normally removes TLS/ACME volumes, but verify before
            # unregistering so the next machine identity cannot reuse them.
            verify_purged_resources(stack.runtime)
        else:
            stack.compose.stop()

        from weave_cli.commands.network_dns import remove_if_configured
        remove_if_configured(stack)

        # Remove only opted-in WEAVE-owned LAN exposure before unregistering.
        if stack.installation.runtime_type == "wsl2" and _state_path(stack.installation.data_directory).exists():
            configure(stack.installation.data_directory, remove=True)

        if purge_volumes:
            # This host marker activates the TLS renewal profile. It must not
            # survive removal of the associated Certbot certificate volume.
            marker = stack.installation.data_directory / "tls.enabled"
            if marker.is_symlink() or (marker.exists() and not marker.is_file()):
                raise PurgeSafetyError("Unexpected TLS marker type; inspect before completing purge.")
            marker.unlink(missing_ok=True)

        # Registration is deleted only after Compose succeeds. Do not erase
        # runtime.env, data directories, distro, or unrelated Docker resources.
        stack.platform.remove_runtime_persistence()
        stack.manager.delete()
        success("WEAVE CBT unregistered; application files were retained.")
        if purge_volumes:
            warning("Compose-managed volumes, TLS certificates and TLS activation marker were removed.")
        else:
            success("Persistent school data volumes were preserved.")
        info("Docker Engine and WSL were not removed.")
    except (*COMMAND_ERRORS, PermissionError, LanError, PurgeSafetyError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="uninstall")(uninstall)
