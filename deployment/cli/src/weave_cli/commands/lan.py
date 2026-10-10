"""Explicit, least-privilege school-LAN forwarding for Windows WSL2 NAT.

Only a school administrator may opt in. The listener binds one selected host
IPv4 address and the firewall accepts one explicit private school subnet.
Never change an unrelated Windows portproxy entry or firewall rule.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import typer

from weave_cli.commands._shared import banner, error, get_stack, info, success, warning

PORT = 80
RULE = "WEAVE-CBT-LAN-TCP80"
DISTRIBUTION = "WeaveCBT"
PRIVATE_RANGES = tuple(ipaddress.IPv4Network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
))


class LanError(RuntimeError):
    """LAN forwarding is unsafe or cannot be configured."""


def _private_address(value: str) -> str:
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise LanError("Supply a valid IPv4 address.") from exc
    if not any(address in network for network in PRIVATE_RANGES):
        raise LanError("The listening address must be a specific private LAN IPv4 address.")
    return str(address)


def _private_subnet(value: str, address: str) -> str:
    try:
        network = ipaddress.IPv4Network(value, strict=True)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
        raise LanError("Supply a valid canonical IPv4 CIDR subnet, e.g. 192.168.1.0/24.") from exc
    # Limit unintended access: one school LAN subnet, not an entire private /8.
    if (not any(network.subnet_of(allowed) for allowed in PRIVATE_RANGES)
            or network.prefixlen < 24 or ipaddress.IPv4Address(address) not in network):
        raise LanError("Client subnet must be private, /24 or narrower, and contain the host LAN address.")
    return str(network)


def _run(args: list[str], *, timeout: int = 30, context: str = "") -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LanError(f"{context or 'Windows network command'} could not complete: {exc}") from exc
    if result.returncode:
        raw_error = (result.stderr or "").strip()
        if raw_error.startswith("#< CLIXML"):
            # Windows PowerShell redirects progress records as XML. Distinguish
            # harmless first-use module progress from a real error record.
            import xml.etree.ElementTree as ET

            diagnostic = ""
            try:
                root = ET.fromstring(raw_error[raw_error.index("<Objs"):])
                records = [
                    " ".join(element.itertext()).strip()
                    for element in root.iter()
                    if element.attrib.get("S", "").lower() == "error"
                ]
                diagnostic = "; ".join(record for record in records if record)
            except (ValueError, ET.ParseError):
                pass
            detail = diagnostic or (result.stdout or "").strip()
            if not detail:
                detail = (
                    "PowerShell exited without an error message; only progress "
                    "metadata was returned. Run the underlying check in an "
                    "elevated PowerShell window to diagnose it."
                )
        else:
            detail = raw_error or (result.stdout or "").strip()
        detail = detail[:1500]
        if not detail:
            detail = (
                "Windows returned no diagnostic text. Inspect Windows Security, "
                "the network profile, IP Helper service and Windows Firewall."
            )
        prefix = f"{context}: " if context else ""
        raise LanError(
            f"{prefix}{Path(args[0]).name} failed (exit {result.returncode}): {detail}"
        )
    return result.stdout.strip()


def _powershell(script: str, *, context: str = "Windows LAN check") -> str:
    """Send a lossless PowerShell script and retain the specific failure reason.

    -EncodedCommand avoids Windows command-line quoting of nested PowerShell
    strings. Terminating and nonterminating errors are written to stderr.
    """
    payload = (
        "$ProgressPreference = 'SilentlyContinue'; "
        "$ErrorActionPreference = 'Stop'; try { " + script
        # An absent firewall rule is an expected result. An explicit exit 0
        # prevents an unsuccessful SilentlyContinue query from leaking an
        # implicit nonzero process status through -EncodedCommand.
        + "; exit 0"
        + " } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
    )
    encoded = base64.b64encode(payload.encode("utf-16le")).decode("ascii")
    return _run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        context=context,
    )


def _wsl_address() -> str:
    output = _run(
        ["wsl.exe", "--distribution", DISTRIBUTION, "--user", "root", "--", "hostname", "-I"]
    )
    addresses = []
    for token in output.split():
        try:
            addr = ipaddress.IPv4Address(token)
        except ipaddress.AddressValueError:
            continue
        if addr.is_private and not addr.is_loopback and not addr.is_link_local:
            addresses.append(str(addr))
    if not addresses:
        raise LanError("Could not determine a private WSL2 IPv4 address.")
    return addresses[0]


def _assert_private_interface(address: str) -> None:
    # Inputs are strictly parsed IPv4 literals: no interpolated PowerShell.
    _powershell(
        "$ip = Get-NetIPAddress -AddressFamily IPv4 -IPAddress '" + address +
        "' -ErrorAction SilentlyContinue; "
        "if (-not $ip) { throw 'Address is not assigned to this Windows host.' }; "
        "$profiles = @($ip | ForEach-Object { "
        "Get-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue }); "
        "if (-not @($profiles | Where-Object { "
        "$_.NetworkCategory -in @('Private','DomainAuthenticated') }).Count) { "
        "throw 'Set the school network profile to Private/Domain before enabling CBT LAN.' }",
        context="Validate LAN interface and network profile",
    )


def _mapped_destination(address: str) -> str | None:
    existing = _powershell(
        "$name = '" + address + "/80'; "
        "$path = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\PortProxy\\v4tov4\\tcp'; "
        "$item = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue; "
        "if ($item) { $entry = $item.PSObject.Properties[$name]; "
        "if ($entry) { [Console]::Out.Write($entry.Value) } }",
        context="Inspect existing Windows port forwarding",
    )
    return existing.strip() or None


def _firewall_exists() -> bool:
    return _powershell(
        "$r = Get-NetFirewallRule -Name '" + RULE +
        "' -ErrorAction SilentlyContinue; if ($r) { 'yes' }",
        context="Inspect WEAVE-owned firewall rule",
    ) == "yes"


def _add_firewall(address: str, subnet: str) -> None:
    _powershell(
        "New-NetFirewallRule -Name '" + RULE +
        "' -DisplayName 'WEAVE CBT - School LAN TCP 80' "
        "-Direction Inbound -Action Allow -Protocol TCP -LocalPort 80 "
        "-LocalAddress '" + address + "' -RemoteAddress '" + subnet +
        "' -Profile Private,Domain -Enabled True | Out-Null",
        context="Create restricted school firewall rule",
    )


def _verify_firewall(address: str, subnet: str) -> None:
    """Verify the *exact* owned firewall scope despite Windows CIDR normalization.

    Windows serializes 192.168.1.0/24 as 192.168.1.0/255.255.255.0 on
    some builds.  Inspect the returned values as networks, never as strings.
    """
    raw = _powershell(
        "$ErrorActionPreference = 'Stop'; "
        "$r = Get-NetFirewallRule -Name '" + RULE + "' -ErrorAction Stop; "
        "$a = $r | Get-NetFirewallAddressFilter; "
        "$p = $r | Get-NetFirewallPortFilter; "
        "$data = @{ "
        "Direction = [string]$r.Direction; Action = [string]$r.Action; "
        "Enabled = [string]$r.Enabled; Profile = [string]$r.Profile; "
        "Protocol = [string]$p.Protocol; "
        "LocalPort = @($p.LocalPort | ForEach-Object { [string]$_ }); "
        "LocalAddress = @($a.LocalAddress | ForEach-Object { [string]$_ }); "
        "RemoteAddress = @($a.RemoteAddress | ForEach-Object { [string]$_ }) "
        "}; ConvertTo-Json -InputObject $data -Compress -Depth 4",
        context="Verify restricted school firewall rule",
    )
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Firewall rule result is not an object.")
        profiles = {x.strip().lower() for x in result["Profile"].split(",")}
        basic = (
            result["Direction"].lower() == "inbound"
            and result["Action"].lower() == "allow"
            and result["Enabled"].lower() == "true"
            and profiles <= {"private", "domain"} and bool(profiles)
            and result["Protocol"].lower() == "tcp"
            and result["LocalPort"] == ["80"]
            and result["LocalAddress"] == [address]
        )
        remote = result["RemoteAddress"]
        network = ipaddress.IPv4Network(subnet, strict=True)
        matches = (
            isinstance(remote, list) and len(remote) == 1
            and ipaddress.IPv4Network(remote[0], strict=True) == network
        )
        if not basic or not matches:
            raise ValueError("Firewall rule metadata/scope mismatch.")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise LanError(
            "WEAVE firewall rule differs from its recorded private LAN scope."
        ) from exc

def _state_path(data: Path) -> Path:
    return data / "lan.json"


def _read_state(data: Path) -> dict[str, str] | None:
    path = _state_path(data)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        address = _private_address(raw["listen_address"])
        subnet = _private_subnet(raw["client_subnet"], address)
        wsl = _private_address(raw["wsl_address"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LanError("Invalid LAN forwarding state. Inspect lan.json before changing Windows networking.") from exc
    return {"listen_address": address, "client_subnet": subnet, "wsl_address": wsl}


def _save_state(data: Path, state: dict[str, str]) -> None:
    path = _state_path(data)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                          prefix=".weave-lan-", suffix=".tmp",
                                          dir=data, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def configure(data: Path, *, listen_address: str | None = None,
              client_subnet: str | None = None, refresh: bool = False,
              remove: bool = False) -> bool:
    """Create/refresh/remove only a verified WEAVE-owned listener.

    Returns False when refreshing an installation without LAN configuration.
    """
    if refresh and remove:
        raise LanError("--refresh and --remove are mutually exclusive.")
    if (refresh or remove) and (listen_address is not None or client_subnet is not None):
        raise LanError("Do not combine --refresh/--remove with address options.")
    stored = _read_state(data)
    if refresh and stored is None:
        return False
    if remove and stored is None:
        return False
    if remove:
        assert stored is not None
        old_ip = stored["listen_address"]
        destination = _mapped_destination(old_ip)
        expected = f'{stored["wsl_address"]}/{PORT}'
        if destination not in (None, expected):
            raise LanError("Portproxy was changed outside WEAVE; refusing to delete an unrelated mapping.")
        firewall = _firewall_exists()
        if firewall:
            _verify_firewall(old_ip, stored["client_subnet"])
        if (data / "tls-lan.json").exists():
            from weave_cli.commands.lan_tls import reconcile

            reconcile(data, remove=True)
        if destination is not None:
            _run(["netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                  "listenport=80", f"listenaddress={old_ip}"])
        if firewall:
            _powershell("Remove-NetFirewallRule -Name '" + RULE + "' -ErrorAction Stop")
        _state_path(data).unlink()
        return True

    if refresh:
        assert stored is not None
        listen_address, client_subnet = stored["listen_address"], stored["client_subnet"]
    elif listen_address is None or client_subnet is None:
        raise LanError("Provide both --listen-address and --client-subnet, or use --refresh.")
    address = _private_address(listen_address)
    subnet = _private_subnet(client_subnet, address)
    if stored and (address, subnet) != (stored["listen_address"], stored["client_subnet"]):
        raise LanError("LAN scope changed. Use 'weave lan --remove' before configuring a new subnet.")
    _assert_private_interface(address)
    destination = _mapped_destination(address)
    if destination and (stored is None or destination != f'{stored["wsl_address"]}/{PORT}'):
        raise LanError("An unrelated portproxy mapping already uses this LAN address/port.")
    firewall = _firewall_exists()
    if firewall and stored is None:
        raise LanError("A firewall rule with WEAVE's name already exists without WEAVE ownership state.")
    if firewall:
        _verify_firewall(address, subnet)
    target_ip = _wsl_address()
    if target_ip == address:
        raise LanError("WSL address matches Windows listener; NAT portproxy is not applicable.")
    previous_removed = False
    new_mapping = False
    firewall_created = False
    try:
        if destination != f"{target_ip}/{PORT}":
            if destination:
                _run(["netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                      "listenport=80", f"listenaddress={address}"])
                previous_removed = True
            _run(["netsh.exe", "interface", "portproxy", "add", "v4tov4",
                  "listenport=80", f"listenaddress={address}", "connectport=80",
                  f"connectaddress={target_ip}"])
            new_mapping = True
        if not firewall:
            _add_firewall(address, subnet)
            firewall_created = True
        _verify_firewall(address, subnet)
        _save_state(data, {"listen_address": address, "client_subnet": subnet, "wsl_address": target_ip})
    except (LanError, OSError) as exc:
        recovery_errors = []
        # Roll back only changes made by this invocation. No unrelated
        # mapping or firewall rule is ever removed.
        if firewall_created:
            try:
                _powershell("Remove-NetFirewallRule -Name '" + RULE + "' -ErrorAction Stop")
            except LanError as recovery:
                recovery_errors.append(str(recovery))
        if new_mapping:
            try:
                _run(["netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                      "listenport=80", f"listenaddress={address}"])
            except LanError as recovery:
                recovery_errors.append(str(recovery))
        if previous_removed:
            try:
                old_ip = destination.rsplit("/", 1)[0]
                _run(["netsh.exe", "interface", "portproxy", "add", "v4tov4",
                      "listenport=80", f"listenaddress={address}", "connectport=80",
                      f"connectaddress={old_ip}"])
            except LanError as recovery:
                recovery_errors.append(str(recovery))
        if recovery_errors:
            raise LanError(
                f"LAN update failed and compensation was incomplete: {exc}. "
                "Inspect portproxy and firewall rules manually: "
                + "; ".join(recovery_errors)
            ) from exc
        raise
    return True


def refresh_if_configured(data: Path, *, runtime_type: str) -> None:
    """Reconcile a previously opted-in LAN listener after WSL starts."""
    if runtime_type == "wsl2" and _state_path(data).exists():
        configure(data, refresh=True)
        if (data / "tls-lan.json").exists():
            from weave_cli.commands.lan_tls import reconcile

            reconcile(data)


def lan(
    listen_address: str | None = typer.Option(None, "--listen-address",
        help="Private Windows host IPv4 address on the school LAN."),
    client_subnet: str | None = typer.Option(None, "--client-subnet",
        help="Allowed private school LAN CIDR (/24 or narrower)."),
    refresh: bool = typer.Option(False, "--refresh", help="Refresh an existing WSL NAT mapping."),
    remove: bool = typer.Option(False, "--remove", help="Remove only WEAVE-owned LAN rules."),
) -> None:
    """Opt in to restricted Windows LAN access for WSL2-hosted CBT."""
    banner("School LAN access")
    try:
        if sys.platform != "win32":
            raise LanError("LAN portproxy management applies only to Windows WSL2.")
        stack = get_stack()
        if stack.installation.runtime_type != "wsl2":
            raise LanError("LAN portproxy management requires the WeaveCBT WSL2 runtime.")
        if not stack.platform.is_admin():
            raise LanError("Run an elevated Administrator PowerShell.")
        changed = configure(stack.installation.data_directory, listen_address=listen_address,
                            client_subnet=client_subnet, refresh=refresh, remove=remove)
        if not changed:
            info("No WEAVE-managed LAN mapping is configured.")
        elif remove:
            success("WEAVE-owned LAN forwarding removed.")
        else:
            success("Restricted LAN forwarding configured. Test from a separate student device.")
            warning("Windows logon is still required to keep the WSL2 runtime alive.")
    except (LanError, OSError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="lan")(lan)
