"""Administrator-approved school adapter binding and profile recovery."""
from __future__ import annotations

import ipaddress
import json
import sys

import typer

from weave_cli.commands import network
from weave_cli.commands.lan import LanError, _powershell
from weave_cli.commands._shared import get_stack, success, error, warning
from weave_cli.networking.state import load_or_import, save

app = typer.Typer(help="Pin and recover the approved school network adapter.")


def _candidate(name: str) -> dict:
    matches = [
        row for row in network.inventory()
        if row["name"].casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise LanError("Select exactly one connected interface with a private IPv4 address.")
    row = matches[0]
    subnet = ipaddress.ip_network(row["network"])
    if (not row["private"] or subnet.prefixlen < 20
            or row["name"].lower().startswith(("vethernet", "wsl", "docker", "vmware", "virtualbox"))
            or not row.get("guid")):
        raise LanError("The preferred school interface must be a physical, uniquely identifiable private adapter.")
    return row


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _profile(row: dict) -> None:
    """Trust only the exact previously inspected GUID and static IPv4 tuple."""
    guid = _ps_quote(row["guid"])
    address = _ps_quote(row["address"])
    subnet = ipaddress.ip_network(row["network"])
    script = (
        "$ErrorActionPreference='Stop';"
        f"$a=Get-NetAdapter -InterfaceDescription (Get-NetAdapter | Where-Object {{ $_.InterfaceGuid.ToString() -eq {guid} }} | Select-Object -First 1).InterfaceDescription -ErrorAction Stop;"
        f"if ($a.InterfaceGuid.ToString() -ne {guid} -or $a.Status -ne 'Up') {{ throw 'Approved network interface not found' }};"
        "$ips=@(Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -ErrorAction Stop);"
        f"if (@($ips | Where-Object {{ $_.IPAddress -eq {address} -and $_.PrefixLength -eq {subnet.prefixlen} }}).Count -ne 1) {{ throw 'Approved static IP changed' }};"
        "$p=Get-NetConnectionProfile -InterfaceIndex $a.ifIndex -ErrorAction Stop;"
        "if ($p.NetworkCategory -eq 'Public') {"
        "  Set-NetConnectionProfile -InterfaceIndex $a.ifIndex -NetworkCategory Private -ErrorAction Stop"
        "} elseif ($p.NetworkCategory -notin @('Private','DomainAuthenticated')) { throw 'Unexpected network profile' }"
    )
    _powershell(script, context="Restore approved school Ethernet profile")


def restore(stack) -> bool:
    if sys.platform != "win32" or stack.installation.runtime_type != "wsl2":
        return False
    data = stack.installation.data_directory
    state = load_or_import(data, runtime_type="wsl2")
    if not state["restore_private"] or not state.get("interface_guid"):
        return False
    if not stack.platform.is_admin():
        raise LanError("Administrator permissions required for approved profile recovery.")
    row = _candidate(state["interface_name"])
    if (row.get("guid", "").casefold() != state["interface_guid"].casefold()
            or row["address"] != state["address"]
            or row["network"] != state["subnet"]):
        raise LanError("Preferred interface identity or school address changed; refusing to trust another network.")
    if row["category"] == "Public":
        _profile(row)
        return True
    if row["category"] not in ("Private", "DomainAuthenticated"):
        raise LanError("Preferred school network has an unrecognized profile.")
    return False


@app.command("set")
def prefer_set(
    interface: str = typer.Option(..., "--interface"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    try:
        stack = get_stack()
        if sys.platform != "win32" or not stack.platform.is_admin():
            raise LanError("Run as Windows Administrator to save the preferred adapter.")
        row = _candidate(interface)
        if not yes and not typer.confirm(
            f"Trust '{row['name']}' at {row['address']} ({row['network']}) and "
            "allow WEAVE to restore Private on login?", default=False
        ):
            return
        state = load_or_import(stack.installation.data_directory, runtime_type="wsl2")
        state.update(
            interface_name=row["name"], interface_guid=row["guid"],
            address=row["address"], subnet=row["network"], restore_private=True,
        )
        if row["category"] == "Public":
            _profile(row)
        elif row["category"] not in ("Private", "DomainAuthenticated"):
            raise LanError("Unrecognized network profile.")
        save(stack.installation.data_directory, state)
        success("Preferred school adapter and approved recovery saved.")
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("status")
def prefer_status() -> None:
    try:
        stack = get_stack()
        state = load_or_import(
            stack.installation.data_directory, runtime_type=stack.installation.runtime_type
        )
        typer.echo(json.dumps({
            key: state.get(key) for key in (
                "interface_name", "interface_guid", "address", "subnet", "restore_private"
            )
        }, indent=2))
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("clear")
def prefer_clear(yes: bool = typer.Option(False, "--yes")) -> None:
    try:
        stack = get_stack()
        if not stack.platform.is_admin():
            raise LanError("Administrator permissions required.")
        if not yes and not typer.confirm(
            "Disable automatic school-adapter profile recovery?", default=False
        ):
            return
        state = load_or_import(
            stack.installation.data_directory, runtime_type=stack.installation.runtime_type
        )
        state.update(interface_name=None, interface_guid=None, restore_private=False)
        save(stack.installation.data_directory, state)
        warning("Automatic adapter profile recovery disabled; existing LAN preserved.")
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(network_app: typer.Typer) -> None:
    network_app.add_typer(app, name="prefer")
