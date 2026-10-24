"""Read-only network inventory and opt-in school LAN setup assistance."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import typer

from weave_cli.commands._shared import COMMAND_ERRORS, banner, error, get_stack, info, success, warning
from weave_cli.commands.lan import MIN_SCHOOL_PREFIX, PRIVATE_RANGES, LanError, _read_state, configure, _powershell
from weave_cli.installation import InstallationStateError
from weave_cli.platforms.base import PlatformError

app = typer.Typer(help="Show local IP/subnet details, check LAN readiness, or configure Windows forwarding.")


NETWORK_INSPECTION_TIMEOUT = 60


def _run(command: list[str]) -> str:
    # Windows PowerShell networking modules can load slowly on older hosts.
    # Retry only read-only inventory queries; never blindly retry mutations.
    attempts = 2 if sys.platform == "win32" else 1
    for attempt in range(attempts):
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=NETWORK_INSPECTION_TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if attempt + 1 < attempts:
                time.sleep(1)
                continue
            raise LanError(
                f"Cannot inspect network adapters: timed out after "
                f"{NETWORK_INSPECTION_TIMEOUT}s per attempt ({attempts} attempt(s)). "
                "Check Windows network services and adapter drivers."
            ) from exc
        except OSError as exc:
            raise LanError(f"Cannot inspect network adapters: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "").strip()[:500]
            raise LanError(
                f"Network inventory command failed (exit {result.returncode})"
                + (f": {detail}" if detail else ".")
            )
        return result.stdout.strip()
    raise AssertionError("Unreachable network inspection state")


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
        and ipaddress.IPv4Network(row["network"]).prefixlen >= MIN_SCHOOL_PREFIX
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
            raise LanError("No unambiguous private /20-or-narrower school network was found.")
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
            if selected:
                address = selected["address"]
            elif _https_hostname(stack):
                # The paired HTTPS hostname is independently verified in the
                # installed Nginx configuration. Showing it does not require
                # guessing an untrusted or ambiguous LAN interface.
                address = ""
            else:
                raise LanError("Choose an unambiguous school network before requesting a student URL.")
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
            if not address:
                warning("No eligible school LAN adapter was detected; verify the server IP and school connectivity independently.")
        warning("Verify student access from a separate school computer.")
    except (*COMMAND_ERRORS, LanError, RuntimeError) as exc:
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
            or ipaddress.IPv4Network(chosen["network"]).prefixlen < MIN_SCHOOL_PREFIX):
        raise LanError("Choose a physical school adapter with a private /20-or-narrower subnet.")
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
    client_subnet: str | None = typer.Option(None, "--client-subnet", help="Allowed private school LAN CIDR (/20 or narrower)."),
    auto: bool = typer.Option(False, "--auto", help="Detect the CIDR from the only eligible trusted school interface."),
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



def _tcp_open(address: str, port: int) -> bool:
    """Test the actual host TCP path, not just saved portproxy metadata."""
    try:
        with socket.create_connection((address, port), timeout=5):
            return True
    except OSError:
        return False


def _expected_ports(data: Path) -> tuple[int, ...]:
    return (80, 443) if (data / "tls.enabled").is_file() else (80,)


def _windows_listening_ports(address: str) -> set[int]:
    """Inspect active Windows TCP listeners bound to the specific school IP."""
    # Address comes from validated WEAVE lan.json (never untrusted PowerShell).
    from weave_cli.commands.lan import _private_address
    address = _private_address(address)
    output = _powershell(
        "$ports = @(Get-NetTCPConnection -LocalAddress '" + address
        + "' -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LocalPort -in @(80,443) } | "
        "ForEach-Object { [int]$_.LocalPort }); "
        "[Console]::Out.Write(($ports -join ','))",
        context="Inspect active school LAN listeners",
    )
    try:
        return {int(value) for value in output.split(",") if value.strip()}
    except ValueError as exc:
        raise LanError("Windows returned invalid TCP listener information.") from exc


def _ip_helper_status() -> str:
    """Read-only check for Windows service responsible for portproxy listeners."""
    return _powershell(
        "(Get-Service -Name 'iphlpsvc' -ErrorAction Stop).Status.ToString()",
        context="Inspect Windows IP Helper",
    ).strip()


def _restart_ip_helper() -> None:
    """Explicit repair only: never invoked by doctor or unattended refresh."""
    state = _ip_helper_status()
    if state == "Running":
        command = "Restart-Service -Name 'iphlpsvc' -ErrorAction Stop"
    elif state == "Stopped":
        command = "Start-Service -Name 'iphlpsvc' -ErrorAction Stop"
    else:
        raise LanError(f"IP Helper state is {state}; inspect the service before attempting repair.")
    _powershell(command, context="Repair Windows IP Helper listener activation")
    if _ip_helper_status() != "Running":
        raise LanError("IP Helper is not running after the attempted repair.")


def _windows_refresh_health(saved: dict[str, str], ports: tuple[int, ...], *,
                            repair: bool) -> None:
    """Validate WEAVE-owned forwarding, optionally restart IP Helper once."""
    from weave_cli.commands import lan
    from weave_cli.commands import lan_tls

    address, target = saved["listen_address"], saved["wsl_address"]
    for port in ports:
        destination = (
            lan._mapped_destination(address) if port == 80
            else lan_tls._destination(address)
        )
        if destination != f"{target}/{port}":
            raise LanError(
                f"TCP/{port} forwarding does not match WEAVE's saved WSL destination; "
                "do not restart IP Helper until the mapping is corrected."
            )
    active = _windows_listening_ports(address)
    reachable = {port: _tcp_open(address, port) for port in ports}
    if all(port in active and reachable[port] for port in ports):
        return
    missing = [port for port in ports if port not in active]
    failures = [port for port in ports if not reachable[port]]
    detail = (
        f"School LAN {address} is not ready; missing active TCP listeners: {missing}; "
        f"failed TCP connections: {failures}."
    )
    if not repair:
        raise LanError(detail + " Run 'weave network refresh --repair' manually as Administrator.")
    if not missing:
        raise LanError(detail + " Listeners exist; an IP Helper restart is not indicated. Check firewall and bindings.")
    # A service restart cannot fix a dead backend or an unowned forwarding rule.
    for port in ports:
        if not _tcp_open(target, port):
            raise LanError(
                f"WSL backend {target}:{port} cannot be reached. "
                "Restore Docker/NGINX before repairing Windows IP Helper."
            )
    warning(
        "Windows portproxy mappings are correct but LAN TCP listeners are missing. "
        "Attempting one IP Helper restart; this can briefly affect other Windows networking services."
    )
    _restart_ip_helper()
    for attempt in range(6):
        current = _windows_listening_ports(address)
        if all(port in current and _tcp_open(address, port) for port in ports):
            success("IP Helper recovery restored the WEAVE school LAN listeners.")
            return
        if attempt != 5:
            time.sleep(0.5)
    raise LanError(
        f"IP Helper was restarted, but {address} did not become reachable "
        f"on all required ports {ports}. Inspect Windows services and firewall."
    )


def _native_refresh_health(data: Path, *, repair: bool) -> None:
    """Linux uses native host/Docker networking; never use Windows repair."""
    if repair:
        warning("IP Helper repair applies only to Windows WSL2; Linux networking is read-only here.")
    candidate = recommend(inventory())
    if not candidate:
        warning("Cannot select one Linux school adapter; run 'weave network status' and verify access manually.")
        return
    address = candidate["address"]
    for port in _expected_ports(data):
        if not _tcp_open(address, port):
            raise LanError(
                f"Native Linux school interface {address}:{port} is not accepting TCP. "
                "Inspect Docker port publishing, NGINX and firewall rules; no Windows portproxy is used."
            )
    success(f"Native Linux school address {address} accepts the configured CBT TCP ports.")


@app.command("refresh")
def network_refresh(
    repair: bool = typer.Option(False, "--repair", help="Interactively requested Windows IP Helper repair when portproxy listeners are absent."),
) -> None:
    """Reconcile Windows forwarding and validate actual LAN TCP reachability.

    Only --repair can attempt an IP Helper restart; unattended refresh is safe.
    Native Linux checks direct TCP reachability and never changes system services.
    """
    try:
        stack = get_stack()
        data = stack.installation.data_directory
        if stack.installation.runtime_type != "wsl2":
            _native_refresh_health(data, repair=repair)
            return
        if not stack.platform.is_admin():
            raise LanError("Administrator permissions are required.")
        if not configure(data, refresh=True):
            warning("No school network mapping is configured.")
            return
        ports = _expected_ports(data)
        if 443 in ports and not (data / "tls-lan.json").is_file():
            raise LanError("HTTPS is enabled but WEAVE's TCP/443 forwarding is not registered. Re-activate WEAVE TLS before repair.")
        if (data / "tls-lan.json").exists():
            from weave_cli.commands.lan_tls import reconcile
            reconcile(data)
        saved = _read_state(data)
        if not saved:
            raise LanError("Saved school network identity is missing after refreshing forwarding.")
        _windows_refresh_health(saved, ports, repair=repair)
        success("WEAVE school LAN forwarding is configured and accepting TCP connections.")
    except (LanError, OSError, InstallationStateError, PlatformError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def _startup_reconcile(stack, *, attempts: int = 5, delay: float = 2.0) -> bool:
    """Reconcile only an opted-in Windows school listener after WSL boots.

    This must never guess an adapter, silently recreate missing ownership state,
    or make runtime startup depend on an unconfigured LAN.
    """
    from weave_cli.commands import lan, lan_tls

    if stack.installation.runtime_type != "wsl2":
        return False
    data = stack.installation.data_directory
    if not (data / "lan.json").exists():
        if (data / "tls-lan.json").exists():
            raise LanError("HTTPS LAN configuration exists without base LAN state; repair manually.")
        return False
    if not stack.platform.is_admin():
        raise LanError("Configured network reconciliation requires Administrator permissions.")

    failures: list[str] = []
    for attempt in range(attempts):
        try:
            # The stored host address and subnet remain authoritative; configure
            # checks the selected host IP and never substitutes another adapter.
            lan.configure(data, refresh=True)
            if (data / "tls-lan.json").exists():
                lan_tls.reconcile(data)
            saved = lan._read_state(data)
            if saved is None:
                raise LanError("Configured LAN state disappeared during reconciliation.")
            ports = _expected_ports(data)
            if 443 in ports and not (data / "tls-lan.json").exists():
                raise LanError("HTTPS requires its saved WEAVE LAN TLS binding.")
            # On the final attempt, allow the existing guarded IP Helper
            # recovery: it restarts the service only for missing listeners
            # after confirming both the rule ownership and WSL backend.
            _windows_refresh_health(saved, ports, repair=attempt == attempts - 1)
            return True
        except (LanError, OSError) as exc:
            failures.append(str(exc))
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise LanError(
        f"Startup network reconciliation failed after {attempts} attempts: {failures[-1]}"
    )


@app.command("startup-reconcile", hidden=True)
def startup_reconcile() -> None:
    """Unattended, bounded school network recovery invoked by the WSL keeper."""
    try:
        stack = get_stack()
        if _startup_reconcile(stack):
            success("Saved WEAVE school network is accepting TCP connections.")
        else:
            info("No school LAN binding configured; skipping network reconciliation.")
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
    """Read-only local, school-IP and backend TCP checks; never repair services."""
    banner("Network diagnostics")
    failed = False
    try:
        adapters = inventory()
        _display(adapters)
        if not adapters:
            failed = True
        selected = recommend(adapters)
        if not selected:
            warning("No unambiguous private school LAN adapter. Check adapter/profile/subnet.")

        try:
            stack = get_stack()
            data = stack.installation.data_directory
            ports = _expected_ports(data)
            for port in ports:
                if _tcp_open("127.0.0.1", port):
                    success(f"Localhost TCP/{port} accepts connections (HTTP contents not verified).")
                else:
                    error(f"Localhost TCP/{port} is unavailable; check Docker and NGINX.")
                    failed = True

            if stack.installation.runtime_type == "wsl2":
                saved = _read_state(data)
                if not saved:
                    warning("Windows school LAN forwarding has not been configured.")
                else:
                    from weave_cli.commands import lan, lan_tls
                    address = saved["listen_address"]
                    try:
                        state = _ip_helper_status()
                        if state == "Running":
                            success("Windows IP Helper service is running.")
                        else:
                            error(f"Windows IP Helper is {state}; manual repair may be needed.")
                            failed = True
                    except LanError as exc:
                        error(str(exc))
                        failed = True

                    if not lan._firewall_exists():
                        error("The WEAVE-owned HTTP Windows Firewall rule is missing.")
                        failed = True
                    else:
                        lan._verify_firewall(address, saved["client_subnet"])
                        success("WEAVE HTTP firewall scope matches the saved school network.")

                    for port in ports:
                        destination = (
                            lan._mapped_destination(address) if port == 80
                            else lan_tls._destination(address)
                        )
                        if destination != f"{saved['wsl_address']}/{port}":
                            error(
                                f"Windows TCP/{port} portproxy does not match the saved WSL "
                                "destination; run 'weave network refresh'."
                            )
                            failed = True
                        if port == 443:
                            if not (data / "tls-lan.json").is_file():
                                error("HTTPS activation exists but the WEAVE TCP/443 forwarding record is missing.")
                                failed = True
                            elif not lan_tls._firewall_exists():
                                error("The WEAVE-owned HTTPS Windows Firewall rule is missing.")
                                failed = True
                            else:
                                lan_tls._verify_firewall(address, saved["client_subnet"])
                                success("WEAVE HTTPS firewall scope matches the school network.")

                    listeners = _windows_listening_ports(address)
                    for port in ports:
                        if port not in listeners:
                            error(
                                f"TCP/{port} has no active Windows listener at {address}. "
                                "If the WSL backend is reachable, run 'weave network refresh --repair' as Administrator."
                            )
                            failed = True
                        if _tcp_open(address, port):
                            success(f"Windows school LAN {address}:{port} accepts TCP connections.")
                        else:
                            error(f"Windows school LAN {address}:{port} refuses TCP connections.")
                            failed = True
                        if _tcp_open(saved["wsl_address"], port):
                            success(f"WSL backend {saved['wsl_address']}:{port} accepts TCP connections.")
                        else:
                            error(f"WSL backend {saved['wsl_address']}:{port} is unreachable; inspect NGINX/Docker.")
                            failed = True
            elif selected:
                address = selected["address"]
                for port in ports:
                    if _tcp_open(address, port):
                        success(f"Native Linux school IP {address}:{port} accepts TCP connections.")
                    else:
                        error(
                            f"Native Linux school IP {address}:{port} is not accepting TCP; "
                            "inspect Docker port publishing and firewall policy."
                        )
                        failed = True
        except (LanError, OSError, InstallationStateError, PlatformError, ValueError) as exc:
            error(str(exc))
            failed = True

        warning("Host-local checks do not prove connectivity from another school computer.")
        if failed:
            raise typer.Exit(code=1)
    except (LanError, ValueError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(root: typer.Typer) -> None:
    from weave_cli.commands.network_dns import register as register_dns
    from weave_cli.commands.client_resolution import register as register_client
    register_dns(app)
    register_client(app)
    root.add_typer(app, name="network")
