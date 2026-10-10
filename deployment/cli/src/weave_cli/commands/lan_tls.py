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


def _firewall(address: str, subnet: str, *, create: bool) -> None:
    if create:
        lan._powershell(
            "New-NetFirewallRule -Name '" + TLS_RULE
            + "' -DisplayName 'WEAVE CBT - School LAN HTTPS' "
            "-Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 "
            "-LocalAddress '" + address + "' -RemoteAddress '" + subnet
            + "' -Profile Private,Domain -Enabled True | Out-Null",
            context="Restrict school HTTPS access",
        )
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
        assert str(result["Direction"]).lower() == "inbound"
        assert str(result["Action"]).lower() == "allow"
        assert str(result["Enabled"]).lower() == "true"
        assert str(result["Protocol"]).lower() == "tcp"
        assert [str(x) for x in result["Port"]] == ["443"]
        assert [str(x) for x in result["Address"]] == [address]
        assert lan.ipaddress.IPv4Network(result["Remote"][0], strict=True) == (
            lan.ipaddress.IPv4Network(subnet, strict=True)
        )
        assert set(p.strip().lower() for p in result["Profile"].split(",")) <= {
            "private", "domain"
        }
    except (AssertionError, KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise lan.LanError("CBT HTTPS firewall does not match the saved school LAN scope") from None


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
    """Create/refresh HTTPS only if the school already opted into LAN forwarding."""
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
    has_rule = _firewall_exists()
    if has_rule:
        _firewall(address, subnet, create=False)
    if remove:
        if destination is not None:
            lan._run(
                ["netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                 "listenport=443", f"listenaddress={address}"]
            )
        if has_rule:
            lan._powershell(
                "Remove-NetFirewallRule -Name '" + TLS_RULE + "' -ErrorAction Stop"
            )
        record.unlink()
        return
    if has_rule and not record.exists():
        raise lan.LanError("HTTPS firewall exists without WEAVE ownership state")
    new_target = lan._wsl_address()
    if destination != f"{new_target}/443":
        if destination is not None:
            lan._run(
                ["netsh.exe", "interface", "portproxy", "delete", "v4tov4",
                 "listenport=443", f"listenaddress={address}"]
            )
        lan._run(
            ["netsh.exe", "interface", "portproxy", "add", "v4tov4",
             "listenport=443", f"listenaddress={address}", "connectport=443",
             f"connectaddress={new_target}"]
        )
    if not has_rule:
        _firewall(address, subnet, create=True)
    _save(
        data,
        {"listen_address": address, "client_subnet": subnet, "wsl_address": new_target},
    )
