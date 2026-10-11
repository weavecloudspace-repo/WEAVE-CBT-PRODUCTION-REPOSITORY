"""Read-only school LAN and DNS guidance for WEAVE CBT administrators."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer


def _configured_lan(data_dir: Path) -> tuple[str | None, str | None]:
    """Read only explicit WEAVE LAN configuration, never runtime.env secrets."""
    try:
        payload = json.loads((data_dir / "lan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    address = payload.get("listen_address")
    subnet = payload.get("client_subnet")
    return (
        address if isinstance(address, str) and address.strip() else None,
        subnet if isinstance(subnet, str) and subnet.strip() else None,
    )


def network_guide() -> None:
    """Show read-only steps for LAN, DNS, HTTPS, and offline exam validation."""
    windows = sys.platform == "win32"
    data_dir = (
        Path(os.getenv("ProgramData", r"C:\ProgramData")) / "WeaveCBT"
        if windows
        else Path("/var/lib/weave-cbt")
    )
    address, subnet = _configured_lan(data_dir)
    typer.echo("WEAVE CBT | School network guide (read-only)")
    typer.echo("No network, firewall, DNS or router settings are changed.")
    if windows:
        typer.echo(f"Configured Windows listener: {address or 'not recorded'}")
        typer.echo(f"Configured client subnet: {subnet or 'not recorded'}")
        typer.echo("Run ipconfig to inspect the host's Ethernet/Wi-Fi IPv4 address.")
        typer.echo("Run netsh interface portproxy show v4tov4 to inspect Windows forwarding.")
        typer.echo("For managed forwarding, configure a Private school network first.")
        typer.echo("WSL2 IP addresses can change after reboot; use weave lan --refresh.")
        typer.echo("Check the exact WEAVE-CBT-LAN-TCP80 and TCP443 Windows Firewall rules.")
    else:
        typer.echo("Run ip -4 addr and ip route to identify the intended school LAN interface.")
        typer.echo("Run ss -lntp to inspect bound ports 80/443.")
        typer.echo("Published Docker ports may bypass UFW INPUT rules; verify from an external client.")
        typer.echo("Use a proper systemd and Polkit agent for privileged Desktop Manager actions.")
    typer.echo("Reserve the server's private IPv4 address in the router's DHCP settings.")
    typer.echo("Configure the paired FQDN as a local DNS A record resolving to that address.")
    typer.echo("Verify DNS from a separate wired and Wi-Fi student device, not just the server.")
    typer.echo("Use the exact paired hostname in HTTPS and validate the complete certificate chain.")
    typer.echo("Never disable certificate verification to hide hostname or trust errors.")
    typer.echo("Test student/staff URLs and login from separate devices on the authorized subnet.")
    typer.echo("After a dry-run and while no exam is active, test service through an internet outage.")
    typer.echo("Local exams should continue on the LAN; WEAVE cloud synchronization needs internet.")


def register(app: typer.Typer) -> None:
    app.command(name="network-guide")(network_guide)
