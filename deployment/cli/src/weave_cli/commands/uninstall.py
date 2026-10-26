"""Unregister the installation and remove Compose containers safely."""

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, error, get_stack, info, success, warning,
)

from weave_cli.commands.lan import configure, LanError, _state_path
from weave_cli.commands.purge_safety import PurgeSafetyError, verify_purged_resources
from weave_cli.commands.purge_cleanup import preflight, cleanup_host, verify_host, clear_active_config
from weave_cli.commands.network_dns import DNSError


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

        # Stop optional public ingress BEFORE tearing down Nginx or volumes.
        from weave_cli.commands.network_ngrok import remove as remove_ngrok
        remove_ngrok(stack, purge=True)
        info("Removing application containers...")
        if purge_volumes:
            # Run host ownership checks BEFORE destroying irreplaceable exam data.
            snapshot = preflight(stack)
            cleanup_host(stack)
            stack.compose.destroy()
            verify_purged_resources(stack.runtime)
            verify_host(stack, snapshot)
        else:
            stack.compose.stop()
            from weave_cli.commands.network_dns import remove_if_configured
            remove_if_configured(stack)
            if stack.installation.runtime_type == "wsl2" and _state_path(stack.installation.data_directory).exists():
                configure(stack.installation.data_directory, remove=True)

        # Keep registration until all resource cleanup and verification succeed.
        stack.platform.remove_runtime_persistence()
        if purge_volumes:
            # Checked paths only. No recursive deletions and no unrelated files.
            clear_active_config(stack.installation.data_directory, stack.installation.install_directory)
        stack.manager.delete()
        success("WEAVE CBT unregistered; installation manager binaries were retained.")
        if purge_volumes:
            warning("Compose-managed volumes, TLS certificates and TLS activation marker were removed.")
        else:
            success("Persistent school data volumes were preserved.")
        info("Docker Engine and WSL were not removed.")
    except (*COMMAND_ERRORS, PermissionError, LanError, DNSError, PurgeSafetyError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="uninstall")(uninstall)
