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



def _reconcile_mirrored_firewall(stack, state: dict) -> None:
    """Converge only WEAVE-owned scoped rules for an explicitly approved school LAN."""
    import ipaddress
    import sys
    from weave_cli.commands.lan import _powershell
    from weave_cli.commands.network_prefer import _candidate, _ps_quote

    if sys.platform != "win32" or stack.installation.runtime_type != "wsl2":
        return
    if not state.get("restore_private") or not state.get("interface_guid"):
        warning("Mirrored firewall setup requires an approved school adapter: weave network prefer set --interface NAME")
        return
    if not stack.platform.is_admin():
        warning("Mirrored firewall reconciliation requires Administrator privileges.")
        return
    row = _candidate(state["interface_name"])
    if (row.get("guid", "").casefold() != state["interface_guid"].casefold()
            or row["address"] != state["address"] or row["network"] != state["subnet"]):
        warning("School adapter identity or subnet changed; refusing firewall modifications.")
        return
    network = ipaddress.ip_network(state["subnet"], strict=True)
    if not network.is_private:
        warning("School subnet is not private; refusing firewall modifications.")
        return
    subnet = _ps_quote(str(network))
    address = _ps_quote(state["address"])
    alias = _ps_quote(row["name"])
    ports = "80,443" if (stack.installation.data_directory / "tls.enabled").is_file() else "80"
    script = (
        "$ErrorActionPreference='Stop';"
        "$name='WEAVE-CBT-MIRRORED-LAN';"
        "$existing=Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue;"
        "if ($existing) {"
        " $a=$existing | Get-NetFirewallAddressFilter;"
        " $p=$existing | Get-NetFirewallPortFilter;"
        " $i=$existing | Get-NetFirewallInterfaceFilter;"
        " if ($existing.Direction -ne 'Inbound' -or $existing.Action -ne 'Allow' -or "
        " $p.Protocol -ne 'TCP' -or $a.RemoteAddress -ne " + subnet + " -or "
        " $a.LocalAddress -ne " + address + " -or "
        " $i.InterfaceAlias -ne " + alias + " -or "
        " (@($p.LocalPort) -join ',') -ne '" + ports + "') {"
        " throw 'Existing WEAVE mirrored firewall rule differs; manual review required' }"
        "} else {"
        " New-NetFirewallRule -Name $name -DisplayName 'WEAVE CBT Mirrored School LAN' "
        " -Direction Inbound -Action Allow -Protocol TCP -LocalPort " + ports +
        " -LocalAddress " + address + " -RemoteAddress " + subnet +
        " -InterfaceAlias " + alias + " -Profile Private -ErrorAction Stop | Out-Null"
        "};"
        "$vm='{40E0AC32-46A5-43A1-A68E-17B7C1D4C7D1}';"
        "if (-not (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue)) "
        "{ throw 'Hyper-V firewall rule cmdlets unavailable; cannot complete mirrored setup' };"
        "$hv=Get-NetFirewallHyperVRule -VMCreatorId $vm -Name 'WEAVE-CBT-MIRRORED-HTTP' "
        "-ErrorAction SilentlyContinue;"
        "if (-not $hv) {"
        " New-NetFirewallHyperVRule -Name 'WEAVE-CBT-MIRRORED-HTTP' "
        "-DisplayName 'WEAVE CBT Mirrored LAN HTTP' -Direction Inbound "
        "-Action Allow -Protocol TCP -LocalPorts " + ports +
        " -RemoteAddresses " + subnet + " -VMCreatorId $vm -ErrorAction Stop | Out-Null"
        "};"
    )
    _powershell(script, context="Reconcile approved mirrored school firewall")
    info("WEAVE-owned mirrored Windows and Hyper-V firewall rules checked.")


def reconcile_access(stack) -> None:
    """Heal network on manual start/restart without running asset migration twice."""
    from weave_cli.commands.network_prefer import restore
    from weave_cli.commands.network_ngrok import reconcile as start_remote
    from weave_cli.commands.lan import refresh_if_configured

    state = load_or_import(
        stack.installation.data_directory, runtime_type=stack.installation.runtime_type
    )
    restore(stack)
    if state["transport"] == "nat":
        refresh_if_configured(
            stack.installation.data_directory,
            runtime_type=stack.installation.runtime_type,
        )
    if state["transport"] == "mirrored":
        try:
            _reconcile_mirrored_firewall(stack, state)
        except Exception as exc:
            warning("Mirrored firewall reconciliation needs attention: " + str(exc))
    try:
        start_remote(stack)
    except Exception as exc:
        warning("Optional ngrok tunnel failed; school LAN remains independent: " + str(exc))


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
