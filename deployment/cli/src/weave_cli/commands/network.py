"""Read-only network inventory and opt-in school LAN setup assistance."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

import typer

from weave_cli.commands._shared import banner, error, get_stack, info, success, warning
from weave_cli.commands.lan import PRIVATE_RANGES, LanError, _read_state, configure, _powershell
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
    suitable = [
        row for row in adapters
        if row["private"]
        and row["category"] in ("Private", "DomainAuthenticated", "Host")
        and not row["name"].lower().startswith(
            ("vethernet", "docker", "wsl", "virtualbox", "vmware")
        )
        and any(
            ipaddress.IPv4Network(row["network"]).subnet_of(parent)
            for parent in PRIVATE_RANGES
        )
        and ipaddress.IPv4Network(row["network"]).prefixlen >= 24
    ]
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


@app.command("interfaces", hidden=True)
def network_interfaces() -> None:
    """List active host IPv4 network adapters."""
    network_info(json_output=False)


@app.command("recommend", hidden=True)
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


@app.command("configure", hidden=True)
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


HOSTNAME = re.compile(r"(?<![a-z0-9-])([a-z0-9-]+\.[a-z0-9-]+\.cbt(?:-staging)?\.weavecloudspace\.com)(?![a-z0-9-])")


def _https_hostname(stack) -> str | None:
    """Read the exact paired hostname from Nginx's activated HTTPS configuration.

    Never read the secret-bearing installation identity file or guess a hostname.
    """
    if not (stack.installation.data_directory / "tls.enabled").is_file():
        return None
    response = stack.compose._run_compose_command(
        command=["exec", "-T", "nginx", "cat", "/etc/nginx/weave-conf/node.conf"]
    )
    configuration = response.stdout
    found = re.search(r"\bserver_name\s+([a-z0-9.-]+)\s*;", configuration)
    hostname = found.group(1) if found else ""
    if not HOSTNAME.fullmatch(hostname) or "listen 443 ssl" not in configuration:
        raise LanError("HTTPS is marked active, but the paired Nginx hostname is unavailable.")
    return hostname


def _student_url(stack, address: str) -> dict:
    hostname = _https_hostname(stack)
    return {
        "url": f"https://{hostname}/student" if hostname else f"http://{address}/student",
        "scheme": "https" if hostname else "http",
        "hostname": hostname,
        "address": address,
        "tls_enabled": bool(hostname),
    }


@app.command("url")
def network_url(
    json_output: bool = typer.Option(False, "--json", help="Output the student URL as JSON for the Desktop Manager."),
) -> None:
    """Display the paired HTTPS hostname once activated, otherwise the LAN HTTP URL."""
    try:
        stack = get_stack()
        if stack.installation.runtime_type == "wsl2":
            saved = _read_state(stack.installation.data_directory)
            if not saved:
                raise LanError("Set up the school network first: weave network setup.")
            address = saved["listen_address"]
        else:
            selected = recommend(inventory())
            if not selected:
                raise LanError("Choose an unambiguous school network before requesting a student URL.")
            address = selected["address"]
        result = _student_url(stack, address)
        if json_output:
            typer.echo(json.dumps(result, separators=(",", ":")))
            return
        banner("Student access link")
        typer.echo(result["url"])
        if not result["tls_enabled"]:
            warning("HTTPS has not been activated; pair the server and run weave tls.")
        else:
            warning("School DNS must resolve this hostname to the server LAN IP.")
        warning("Verify student access from a separate school computer.")
    except (LanError, OSError, InstallationStateError, PlatformError, RuntimeError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("status")
def network_status(
    json_output: bool = typer.Option(False, "--json", help="Machine-readable network inventory and saved setup."),
) -> None:
    """Show network identity, approved mapping, and TLS state without changing the host."""
    try:
        adapters = inventory()
        selected = recommend(adapters)
        try:
            stack = get_stack()
            mapping = _read_state(stack.installation.data_directory) if stack.installation.runtime_type == "wsl2" else None
            tls_active = (stack.installation.data_directory / "tls.enabled").is_file()
        except (InstallationStateError, PlatformError, OSError):
            mapping, tls_active = None, False
        snapshot = {"interfaces": adapters, "recommended": selected,
                    "school_network": mapping, "tls_enabled": tls_active}
        if json_output:
            typer.echo(json.dumps(snapshot, separators=(",", ":")))
            return
        banner("School network")
        _display(adapters)
        if mapping:
            info(f"Saved school listener: {mapping['listen_address']} ({mapping['client_subnet']})")
        else:
            warning("School forwarding is not configured on Windows, or not required on Linux.")
        info("HTTPS activation: " + ("configured" if tls_active else "not configured"))
    except (LanError, ValueError, OSError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def _candidate(adapters: list[dict], interface: str) -> dict:
    candidates = [a for a in adapters if a["name"].casefold() == interface.casefold()]
    if len(candidates) != 1:
        raise LanError("Select exactly one connected network adapter by its displayed name.")
    chosen = candidates[0]
    if (not chosen["private"] or chosen["name"].lower().startswith(
        ("vethernet", "docker", "wsl", "virtualbox", "vmware")
    ) or not any(ipaddress.IPv4Network(chosen["network"]).subnet_of(parent)
                 for parent in PRIVATE_RANGES)
            or ipaddress.IPv4Network(chosen["network"]).prefixlen < 24):
        raise LanError("Choose a physical school adapter with a private /24-or-narrower subnet.")
    return chosen


@app.command("trust")
def network_trust(
    interface: str = typer.Option(..., "--interface", help="Exact school Wi-Fi/Ethernet adapter name."),
    yes: bool = typer.Option(False, "--yes", help="Confirm this network is owned or trusted by the school."),
) -> None:
    """Approve one school network before changing its Windows profile to Private."""
    try:
        stack = get_stack()
        if stack.installation.runtime_type != "wsl2" or sys.platform != "win32":
            raise LanError("Changing Windows network profiles is supported on Windows WSL2 only.")
        if not stack.platform.is_admin():
            raise LanError("Run this command from Administrator PowerShell.")
        chosen = _candidate(inventory(), interface)
        if chosen["category"] in ("Private", "DomainAuthenticated"):
            success("The selected school network is already trusted.")
            return
        if chosen["category"] != "Public":
            raise LanError("The selected network has an unsupported profile.")
        if not yes and not typer.confirm(
            f"Trust school network '{chosen['name']}' ({chosen['network']}) and change its Windows profile to Private?",
            default=False,
        ):
            warning("No network settings changed.")
            return
        # Use the verified host IP to resolve interface index; never interpolate user text.
        address = chosen["address"]
        _powershell(
            "$ip=Get-NetIPAddress -AddressFamily IPv4 -IPAddress '" + address + "' -ErrorAction Stop; "
            "if (@($ip).Count -ne 1) { throw 'Ambiguous school IP' }; "
            "$p=Get-NetConnectionProfile -InterfaceIndex $ip.InterfaceIndex -ErrorAction Stop; "
            "if ($p.NetworkCategory -ne 'Public') { throw 'Network profile changed; retry after inspection' }; "
            "Set-NetConnectionProfile -InterfaceIndex $ip.InterfaceIndex -NetworkCategory Private -ErrorAction Stop",
            context="Approve trusted school network",
        )
        success("Approved school network is now Private. Run weave network setup.")
    except (LanError, OSError, InstallationStateError, PlatformError, ValueError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("setup")
def network_setup(
    listen_address: str | None = typer.Option(None, "--listen-address", help="Server IPv4 address."),
    client_subnet: str | None = typer.Option(None, "--client-subnet", help="Allowed school subnet."),
    auto: bool = typer.Option(False, "--auto", help="Use the only eligible trusted school interface."),
    yes: bool = typer.Option(False, "--yes", help="Skip the LAN setup confirmation."),
) -> None:
    """Configure WEAVE-owned Windows forwarding; Linux needs no WSL forwarding."""
    try:
        stack = get_stack()
        if stack.installation.runtime_type != "wsl2":
            banner("School network")
            success("Native Linux does not require Windows-to-WSL forwarding.")
            warning("Verify firewall and student access on the actual school network.")
            return
        if not stack.platform.is_admin():
            raise LanError("Run from Administrator PowerShell.")
        if auto and (listen_address is not None or client_subnet is not None):
            raise LanError("Use either --auto or explicit address/subnet options.")
        if auto:
            selected = recommend(inventory())
            if not selected:
                raise LanError("No single trusted school network found. Use weave network status and, if necessary, weave network trust.")
            listen_address, client_subnet = selected["address"], selected["network"]
        if not listen_address or not client_subnet:
            raise LanError("Supply --auto or both --listen-address and --client-subnet.")
        if not yes and not typer.confirm(
            f"Configure WEAVE network access at {listen_address} for {client_subnet}?", default=False
        ):
            warning("No network settings changed.")
            return
        configure(stack.installation.data_directory, listen_address=listen_address, client_subnet=client_subnet)
        if (stack.installation.data_directory / "tls-lan.json").exists():
            from weave_cli.commands.lan_tls import reconcile
            reconcile(stack.installation.data_directory)
        success("School networking configured. Test from a student device.")
    except (LanError, OSError, InstallationStateError, PlatformError, ValueError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("refresh")
def network_refresh() -> None:
    """Refresh only the saved WEAVE-owned forwarding rules after WSL restarts."""
    try:
        stack = get_stack()
        if stack.installation.runtime_type != "wsl2":
            info("Native Linux does not need Windows forwarding.")
            return
        if not stack.platform.is_admin():
            raise LanError("Administrator permissions are required.")
        if not configure(stack.installation.data_directory, refresh=True):
            warning("No school network mapping is configured.")
            return
        if (stack.installation.data_directory / "tls-lan.json").exists():
            from weave_cli.commands.lan_tls import reconcile
            reconcile(stack.installation.data_directory)
        success("WEAVE network forwarding refreshed.")
    except (LanError, OSError, InstallationStateError, PlatformError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("remove")
def network_remove(
    yes: bool = typer.Option(False, "--yes", help="Confirm removal of only WEAVE-owned forwarding."),
) -> None:
    """Remove WEAVE-owned Windows LAN mappings, without touching unrelated rules."""
    try:
        stack = get_stack()
        if stack.installation.runtime_type != "wsl2":
            raise LanError("Windows port forwarding is not used on native Linux.")
        if not stack.platform.is_admin():
            raise LanError("Administrator permissions are required.")
        if not yes and not typer.confirm("Remove WEAVE school LAN access? Student connections will stop.", default=False):
            return
        if configure(stack.installation.data_directory, remove=True):
            success("WEAVE-owned LAN access removed.")
        else:
            warning("No WEAVE forwarding rules were configured.")
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
                        error("Windows portproxy differs from the saved mapping; run 'weave network refresh'.")
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
    from weave_cli.commands.network_dns import register as register_dns
    register_dns(app)
    root.add_typer(app, name="network")
