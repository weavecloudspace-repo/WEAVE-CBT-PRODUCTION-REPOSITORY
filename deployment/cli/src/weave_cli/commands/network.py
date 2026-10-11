"""Read-only network inventory and opt-in school LAN setup assistance."""
from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import sys
from pathlib import Path

import typer

from weave_cli.commands._shared import banner, error, get_stack, info, success, warning
from weave_cli.commands.lan import LanError, _read_state, configure
from weave_cli.installation import InstallationStateError
from weave_cli.platforms.base import PlatformError

app = typer.Typer(help="Show local IP/subnet details, check LAN readiness, or configure Windows forwarding.")


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LanError(f"Cannot inspect network adapters: {type(exc).__name__}") from exc
    if result.returncode:
        raise LanError(f"Network inventory command failed (exit {result.returncode}).")
    return result.stdout.strip()


def _windows_addresses() -> list[dict]:
    script = (
        "$ErrorActionPreference='Stop';"
        "$result=@(Get-NetIPConfiguration -All | Where-Object { $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up' } | "
        "ForEach-Object { "
        "$ip=@($_.IPv4Address)[0]; $gw=@($_.IPv4DefaultGateway); "
        "$prof=Get-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{ name=$_.InterfaceAlias; address=$ip.IPAddress; prefix=[int]$ip.PrefixLength; "
        "gateway=$(if($gw.Count){$gw[0].NextHop}else{''}); "
        "category=$(if($prof){$prof.NetworkCategory.ToString()}else{'Unknown'}) } "
        "}); ConvertTo-Json -InputObject $result -Compress -Depth 3"
    )
    import base64
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = json.loads(_run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]) or "[]")
    return result if isinstance(result, list) else [result]


def _linux_addresses() -> list[dict]:
    addresses = json.loads(_run(["ip", "-j", "-4", "address", "show", "up"]) or "[]")
    routes = json.loads(_run(["ip", "-j", "-4", "route", "show", "default"]) or "[]")
    gateway = {row.get("dev"): row.get("gateway", "") for row in routes if isinstance(row, dict)}
    found = []
    for item in addresses:
        name = str(item.get("ifname", ""))
        if name == "lo" or name.startswith(("docker", "veth", "br-", "virbr")):
            continue
        for addr in item.get("addr_info", []):
            if addr.get("family") != "inet":
                continue
            found.append({
                "name": name, "address": addr.get("local", ""),
                "prefix": addr.get("prefixlen"), "gateway": gateway.get(name, ""),
                "category": "Host",
            })
    return found


def inventory() -> list[dict]:
    """Retrieve actual host adapters, not private WSL Docker bridge addresses."""
    data = _windows_addresses() if sys.platform == "win32" else _linux_addresses()
    result = []
    for candidate in data:
        try:
            interface = ipaddress.IPv4Interface(f"{candidate['address']}/{candidate['prefix']}")
        except (ValueError, KeyError, TypeError):
            continue
        if interface.ip.is_loopback or interface.ip.is_link_local:
            continue
        result.append({
            "name": str(candidate.get("name") or "Unknown"),
            "address": str(interface.ip),
            "subnet_mask": str(interface.netmask),
            "network": str(interface.network),
            "gateway": str(candidate.get("gateway") or "Not available"),
            "category": str(candidate.get("category") or "Unknown"),
            "private": interface.ip.is_private,
        })
    return result


def recommend(adapters: list[dict]) -> dict | None:
    """Prefer a private active physical subnet; never auto-select an ambiguous tie."""
    suitable = [row for row in adapters
                if row["private"] and row["category"] in ("Private", "DomainAuthenticated", "Host")
                and ipaddress.IPv4Network(row["network"]).prefixlen >= 24]
    # A multi-adapter school server needs explicit choice; guessing is unsafe.
    return suitable[0] if len(suitable) == 1 else None


def _display(adapters: list[dict]) -> None:
    if not adapters:
        warning("No active IPv4 adapters found.")
        return
    for row in adapters:
        typer.echo(
            f"\n{row['name']}  [{row['category']}]\n"
            f"  IP address:   {row['address']}\n"
            f"  Subnet mask:  {row['subnet_mask']}\n"
            f"  Network CIDR: {row['network']}\n"
            f"  Gateway:      {row['gateway']}"
        )


@app.command("info")
def network_info(
    json_output: bool = typer.Option(False, "--json", help="Return machine-readable adapter inventory."),
) -> None:
    """Show host IPv4 addresses, subnet masks, CIDR ranges and gateways."""
    try:
        interfaces = inventory()
        selected = recommend(interfaces)
        if json_output:
            typer.echo(json.dumps({"interfaces": interfaces, "recommended": selected}, separators=(",", ":")))
            return
        banner("Network information")
        _display(interfaces)
        if selected:
            success(f"Suggested school LAN: {selected['address']}  ({selected['network']})")
        elif interfaces:
            warning("Select a school adapter manually; no unambiguous safe recommendation.")
    except (LanError, ValueError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("interfaces")
def network_interfaces() -> None:
    """List active host IPv4 network adapters."""
    network_info(json_output=False)


@app.command("recommend")
def network_recommend() -> None:
    """Show a safe suggested Windows LAN address and subnet, without changing settings."""
    try:
        selected = recommend(inventory())
        banner("Suggested school network")
        if not selected:
            warning("Cannot safely select one adapter. Run 'weave network interfaces' and choose manually.")
            raise typer.Exit(code=1)
        info(f"IP address: {selected['address']}")
        info(f"Client subnet: {selected['network']}")
        if sys.platform == "win32":
            info(f"To enable, run: weave lan --listen-address {selected['address']} --client-subnet {selected['network']}")
            warning("This is a suggestion only; administrator authorization and firewall checks are still required.")
        else:
            warning("Linux uses native Docker networking; Windows portproxy is not applicable.")
    except (LanError, ValueError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("configure")
def network_configure(
    auto: bool = typer.Option(False, "--auto", help="Use the single unambiguous private school adapter."),
) -> None:
    """Explicitly confirm and create a WEAVE-owned Windows WSL2 LAN mapping."""
    if not auto:
        error("Use --auto to inspect and confirm the suggested adapter. For manual setup use 'weave lan'.")
        raise typer.Exit(code=2)
    try:
        if sys.platform != "win32":
            raise LanError("Automatic Windows forwarding applies only to WSL2.")
        selected = recommend(inventory())
        if not selected:
            raise LanError("No unambiguous private /24-or-narrower school network was found.")
        stack = get_stack()
        if stack.installation.runtime_type != "wsl2" or not stack.platform.is_admin():
            raise LanError("Use an elevated Administrator PowerShell with the WEAVE WSL2 installation.")
        banner("Confirm school LAN setup")
        info(f"Listener: {selected['address']}:80")
        info(f"Permitted client subnet: {selected['network']}")
        if not typer.confirm("Apply WEAVE-only port forwarding and firewall rules?", default=False):
            warning("No network changes made.")
            return
        configure(stack.installation.data_directory,
                  listen_address=selected["address"], client_subnet=selected["network"])
        success("WEAVE LAN mapping configured; verify from another student device.")
    except (LanError, OSError, InstallationStateError, PlatformError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("url")
def network_url() -> None:
    """Display a student URL, distinguishing configured Windows forwarding from a suggestion."""
    try:
        stack = get_stack()
        selected = recommend(inventory())
        if stack.installation.runtime_type == "wsl2":
            saved = _read_state(stack.installation.data_directory)
            if not saved:
                warning("No WEAVE-owned school LAN mapping is configured. Use 'weave network recommend'.")
                raise typer.Exit(code=1)
            address = saved["listen_address"]
        else:
            if not selected:
                raise LanError("Select an adapter explicitly; automatic LAN URL is ambiguous.")
            address = selected["address"]
        banner("Student access link")
        typer.echo(f"http://{address}/student")
        warning("This is an HTTP address; use your verified HTTPS hostname when HTTPS is enabled.")
        warning("A working server-local URL does not prove student devices can connect.")
    except (LanError, OSError, InstallationStateError, PlatformError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("doctor")
def network_doctor() -> None:
    """Run read-only checks for active host IP, local HTTP and configured forwarding."""
    banner("Network diagnostics")
    failed = False
    try:
        adapters = inventory()
        _display(adapters)
        if not adapters:
            failed = True
        suggestion = recommend(adapters)
        if not suggestion:
            warning("No unambiguous private school LAN adapter. Check adapter/profile/subnet.")
        try:
            with socket.create_connection(("127.0.0.1", 80), timeout=3):
                success("TCP port 80 is accepting local connections (HTTP contents not verified).")
        except OSError:
            error("TCP port 80 is not reachable locally. Check NGINX, Docker and port binding.")
            failed = True
        try:
            stack = get_stack()
            if stack.installation.runtime_type == "wsl2":
                saved = _read_state(stack.installation.data_directory)
                if not saved:
                    warning("Windows school LAN forwarding has not been configured.")
                else:
                    from weave_cli.commands.lan import _mapped_destination, _firewall_exists, _verify_firewall
                    if _mapped_destination(saved["listen_address"]) != f"{saved['wsl_address']}/80":
                        error("Windows portproxy differs from the saved mapping; run 'weave lan --refresh'.")
                        failed = True
                    if not _firewall_exists():
                        error("The WEAVE-owned Windows Firewall rule is missing.")
                        failed = True
                    else:
                        _verify_firewall(saved["listen_address"], saved["client_subnet"])
                        success("WEAVE-owned LAN firewall scope matches the saved configuration.")
        except (LanError, OSError, InstallationStateError, PlatformError) as exc:
            error(str(exc))
            failed = True
        warning("Final connectivity must be tested from a separate school computer.")
        if failed:
            raise typer.Exit(code=1)
    except (LanError, ValueError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(root: typer.Typer) -> None:
    root.add_typer(app, name="network")
