"""Unattended network reconciliation registered by the new CLI manager.

Runs after the existing user-owned elevated WSL Keeper starts Docker. No
container restart on the ordinary healthy path; only changed packaged assets
use Compose up, which reconciles changed service definitions.
"""
from __future__ import annotations

import json

import typer

from weave_cli.commands._shared import get_stack, error, info, warning, success
from weave_cli.networking.deployment import apply as upgrade_deployment
from weave_cli.networking.state import load_or_import

app = typer.Typer(help="Show or plan WSL networking mode changes.")


def reconcile(stack) -> None:
    from weave_cli.commands.network_prefer import restore
    from weave_cli.commands.network_ngrok import reconcile as start_remote
    from weave_cli.commands.network import _startup_reconcile

    upgrade_deployment(stack)
    state = load_or_import(
        stack.installation.data_directory, runtime_type=stack.installation.runtime_type
    )
    restore(stack)
    if state["transport"] == "nat":
        _startup_reconcile(stack)
    elif state["transport"] == "mirrored":
        # Never run the NAT/portproxy maintenance algorithm on mirrored WSL.
        info("Using approved mirrored WSL transport; skipping portproxy repair.")
    try:
        start_remote(stack)
    except Exception as exc:
        # Internet access is OPTIONAL and must not disable a school LAN.
        warning("Ngrok recovery was not successful: " + str(exc))


def _mode_status(stack) -> dict:
    state = load_or_import(
        stack.installation.data_directory,
        runtime_type=stack.installation.runtime_type,
    )
    return {"effective": state["transport"], "preferred": state["transport"],
            "school_ip": state["address"], "auto_switch_on_startup": False}


@app.command("boot-reconcile", hidden=True)
def boot_reconcile() -> None:
    try:
        stack = get_stack()
        if not stack.platform.is_admin():
            raise RuntimeError("Network boot reconciliation requires elevated startup task.")
        reconcile(stack)
        success("Startup reconciliation completed.")
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("mode-status", hidden=True)
def mode_status_alias() -> None:
    try:
        typer.echo(json.dumps(_mode_status(get_stack()), indent=2))
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("mode-plan", hidden=True)
def mode_plan_alias() -> None:
    try:
        state = _mode_status(get_stack())
        typer.echo(json.dumps({
            **state,
            "mirrored_requires_windows_11_22h2_or_later": True,
            "requires_wsl_shutdown": True,
            "requires_external_student_device_validation": True,
            "mode_change_is_maintenance_only": True,
        }, indent=2))
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(network_app: typer.Typer) -> None:
    network_app.command("boot-reconcile", hidden=True)(boot_reconcile)
    mode = typer.Typer(help="Inspect the selected WSL network mode.")
    mode.command("status")(mode_status_alias)
    mode.command("plan")(mode_plan_alias)
    network_app.add_typer(mode, name="mode")
