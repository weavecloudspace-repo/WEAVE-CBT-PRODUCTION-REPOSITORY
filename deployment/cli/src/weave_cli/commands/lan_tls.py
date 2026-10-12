"""Least-privilege TCP/443 Windows WSL2 NAT forwarding, separate from TCP/80."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from weave_cli.commands import lan

TLS_RULE = "WEAVE-CBT-LAN-TCP443"
TLS_PORT = "443"


def _destination(address: str) -> str | None:
    value = lan._powershell(
        "$name = '" + address + "/443'; "
        "$path = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\PortProxy\\v4tov4\\tcp'; "
        "$item = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue; "
        "if ($item) { $entry = $item.PSObject.Properties[$name]; "
        "if ($entry) { [Console]::Out.Write($entry.Value) } }",
        context="Inspect existing HTTPS forwarding",
    )
    return value.strip() or None


def _firewall_exists() -> bool:
    return lan._powershell(
        "$r = Get-NetFirewallRule -Name '" + TLS_RULE
        + "' -ErrorAction SilentlyContinue; if ($r) { 'yes' }",
        context="Inspect CBT HTTPS firewall rule",
    ) == "yes"


def _create_firewall(address: str, subnet: str) -> None:
    lan._powershell(
        "New-NetFirewallRule -Name '" + TLS_RULE
        + "' -DisplayName 'WEAVE CBT - School LAN HTTPS' "
        "-Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 "
        "-LocalAddress '" + address + "' -RemoteAddress '" + subnet
        + "' -Profile Private,Domain -Enabled True | Out-Null",
        context="Restrict school HTTPS access",
    )


def _verify_firewall(address: str, subnet: str) -> None:
    """Verify every owned-rule constraint before use or deletion."""
    raw = lan._powershell(
        "$r = Get-NetFirewallRule -Name '" + TLS_RULE + "' -ErrorAction Stop; "
        "$a = $r | Get-NetFirewallAddressFilter; "
        "$p = $r | Get-NetFirewallPortFilter; "
        "$data = @{ Direction=[string]$r.Direction; Action=[string]$r.Action; "
        "Enabled=[string]$r.Enabled; Profile=[string]$r.Profile; "
        "Protocol=[string]$p.Protocol; "
        "Port=@($p.LocalPort); Address=@($a.LocalAddress); "
        "Remote=@($a.RemoteAddress) }; "
        "ConvertTo-Json -InputObject $data -Compress -Depth 3",
        context="Verify CBT HTTPS firewall",
    )
    try:
        result = json.loads(raw)
        profiles = {item.strip().lower() for item in result["Profile"].split(",")}
        remote = result["Remote"]
        valid = (
            result["Direction"].lower() == "inbound"
            and result["Action"].lower() == "allow"
            and result["Enabled"].lower() == "true"
            and result["Protocol"].lower() == "tcp"
            and result["Port"] == ["443"]
            and result["Address"] == [address]
            and profiles <= {"private", "domain"} and bool(profiles)
            and isinstance(remote, list) and len(remote) == 1
            and lan.ipaddress.IPv4Network(remote[0], strict=True)
            == lan.ipaddress.IPv4Network(subnet, strict=True)
        )
        if not valid:
            raise ValueError("Firewall rule metadata/scope mismatch")
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise lan.LanError(
            "CBT HTTPS firewall does not match the saved school LAN scope"
        ) from exc


def _state_path(data: Path) -> Path:
    return data / "tls-lan.json"


def _save(data: Path, value: dict[str, str]) -> None:
    fd, name = tempfile.mkstemp(prefix=".tls-lan-", suffix=".tmp", dir=data)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, _state_path(data))
    finally:
        Path(name).unlink(missing_ok=True)


def reconcile(data: Path, *, remove: bool = False) -> None:
    """Reconcile only WEAVE-owned HTTPS forwarding; compensate failed writes."""
    base = lan._read_state(data)
    record = _state_path(data)
    if remove and not record.exists():
        return
    if base is None and not remove:
        raise lan.LanError("Run 'weave lan' to select a trusted school subnet first.")

    if record.exists():
        try:
            saved = json.loads(record.read_text(encoding="utf-8"))
            address = lan._private_address(saved["listen_address"])
            subnet = lan._private_subnet(saved["client_subnet"], address)
            old_target = lan._private_address(saved["wsl_address"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise lan.LanError("Saved CBT HTTPS forwarding state is invalid") from exc
    else:
        if remove:
            return
        assert base is not None
        address, subnet = base["listen_address"], base["client_subnet"]
        old_target = lan._wsl_address()

    if not remove:
        assert base is not None
        if (address, subnet) != (base["listen_address"], base["client_subnet"]):
            raise lan.LanError("HTTPS forwarding scope differs from the school LAN")
        lan._assert_private_interface(address)

    destination = _destination(address)
    if destination not in (None, f"{old_target}/443"):
        raise lan.LanError("TCP/443 belongs to another application; refusing to overwrite it")
    if destination is not None and not record.exists():
        raise lan.LanError("TCP/443 mapping exists without WEAVE ownership state")

    has_rule = _firewall_exists()
    if has_rule:
        _verify_firewall(address, subnet)

    if remove:
        if destination is not None:
            lan._run(
                ["netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                 "listenport=443", f"listenaddress={address}"]
            )
        if has_rule:
            lan._powershell(
                "Remove-NetFirewallRule -Name '" + TLS_RULE + "' -ErrorAction Stop",
                context="Remove owned school HTTPS firewall rule",
            )
        record.unlink()
        return

    if has_rule and not record.exists():
        raise lan.LanError("HTTPS firewall exists without WEAVE ownership state")

    new_target = lan._wsl_address()
    if new_target == address:
        raise lan.LanError("WSL address matches Windows listener; NAT is not applicable")

    previous_removed = False
    mapping_added = False
    firewall_created = False
    try:
        if destination != f"{new_target}/443":
            if destination is not None:
                lan._run(
                    ["netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                     "listenport=443", f"listenaddress={address}"]
                )
                previous_removed = True
            lan._run(
                ["netsh.exe", "interface", "portproxy", "add", "v4tov4",
                 "listenport=443", f"listenaddress={address}", "connectport=443",
                 f"connectaddress={new_target}"]
            )
            mapping_added = True
        if not has_rule:
            _create_firewall(address, subnet)
            firewall_created = True
        _verify_firewall(address, subnet)
        _save(
            data,
            {"listen_address": address, "client_subnet": subnet, "wsl_address": new_target},
        )
    except (lan.LanError, OSError) as exc:
        recovery_errors: list[str] = []
        if firewall_created:
            try:
                lan._powershell(
                    "Remove-NetFirewallRule -Name '" + TLS_RULE + "' -ErrorAction Stop",
                    context="Roll back CBT HTTPS firewall",
                )
            except lan.LanError as recovery:
                recovery_errors.append(str(recovery))
        if mapping_added:
            try:
                lan._run(
                    ["netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                     "listenport=443", f"listenaddress={address}"]
                )
            except lan.LanError as recovery:
                recovery_errors.append(str(recovery))
        if previous_removed:
            try:
                lan._run(
                    ["netsh.exe", "interface", "portproxy", "add", "v4tov4",
                     "listenport=443", f"listenaddress={address}",
                     "connectport=443", f"connectaddress={old_target}"]
                )
            except lan.LanError as recovery:
                recovery_errors.append(str(recovery))
        if recovery_errors:
            raise lan.LanError(
                f"HTTPS forwarding failed and compensation was incomplete: {exc}. "
                "Inspect Windows portproxy/firewall manually: "
                + "; ".join(recovery_errors)
            ) from exc
        raise
