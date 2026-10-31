"""Least-privilege firewall ownership for approved WSL mirrored school networks.

Never change global firewall defaults or arbitrary rules. The school administrator
must have previously pinned a physical interface through 'weave network prefer set'.
"""
from __future__ import annotations

import ipaddress
import json
import sys

from weave_cli.commands import lan

WINDOWS_RULE = "WEAVE-CBT-MIRRORED-LAN"
HYPERV_RULE = "WEAVE-CBT-MIRRORED"
WSL_GUID = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"
LEGACY_WRONG_RULE = "WEAVE-CBT-MIRRORED-HTTP"
LEGACY_WRONG_GUID = "{40E0AC32-46A5-43A1-A68E-17B7C1D4C7D1}"
PORTS = ("80", "443")


class MirroredFirewallError(lan.LanError):
    pass


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _approved(stack, state: dict, *, require_admin: bool = True) -> tuple[str, str, str]:
    """No implicit adapter guessing, trust escalation or public-subnet exposure."""
    from weave_cli.commands.network_prefer import _candidate
    if sys.platform != "win32" or stack.installation.runtime_type != "wsl2":
        raise MirroredFirewallError("Mirrored firewall management requires Windows WSL2.")
    if require_admin and not stack.platform.is_admin():
        raise MirroredFirewallError("Administrator permissions are required for mirrored firewall management.")
    if not state.get("restore_private") or not state.get("interface_guid") or not state.get("interface_name"):
        raise MirroredFirewallError("Approve the school interface first: weave network prefer set --interface NAME.")
    ip = lan._private_address(state.get("address"))
    subnet = lan._private_subnet(state.get("subnet"), ip)
    adapter = _candidate(state["interface_name"])
    if (adapter.get("guid", "").casefold() != state["interface_guid"].casefold()
            or adapter["address"] != ip or adapter["network"] != subnet):
        raise MirroredFirewallError("Approved school interface identity or subnet has changed; no firewall settings modified.")
    if adapter["category"] not in ("Private", "DomainAuthenticated"):
        raise MirroredFirewallError("The approved school interface must have a trusted Windows profile.")
    return ip, subnet, adapter["name"]


def _snapshot() -> dict:
    """Inspect only the two WEAVE rule names, never enumerate or modify others."""
    script = (
        "$ErrorActionPreference='Stop';"
        "if (-not (Get-Command Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue)) "
        "{ throw 'WSL Hyper-V firewall cmdlets are unavailable' };"
        "$data=@{windows=$null;hyperv=$null;orphan=$null};"
        "$w=@(Get-NetFirewallRule -Name '" + WINDOWS_RULE + "' -ErrorAction SilentlyContinue);"
        "if ($w.Count -gt 1) { throw 'Ambiguous WEAVE Windows firewall rule' };"
        "if ($w.Count -eq 1) {"
        " $a=$w[0]|Get-NetFirewallAddressFilter;"
        " $p=$w[0]|Get-NetFirewallPortFilter;"
        " $i=$w[0]|Get-NetFirewallInterfaceFilter;"
        " $data.windows=@{Direction=[string]$w[0].Direction;Action=[string]$w[0].Action;"
        " Enabled=[string]$w[0].Enabled;Profile=[string]$w[0].Profile;"
        " Protocol=[string]$p.Protocol;Ports=@($p.LocalPort);"
        " Local=@($a.LocalAddress);Remote=@($a.RemoteAddress);"
        " Interface=@($i.InterfaceAlias)};"
        "};"
        "$h=@(Get-NetFirewallHyperVRule -Name '" + HYPERV_RULE + "' -ErrorAction SilentlyContinue);"
        "if ($h.Count -gt 1) { throw 'Ambiguous WEAVE Hyper-V firewall rule' };"
        "if ($h.Count -eq 1) {"
        " $data.hyperv=@{Direction=[string]$h[0].Direction;Action=[string]$h[0].Action;"
        " Enabled=[string]$h[0].Enabled;Protocol=[string]$h[0].Protocol;"
        " Creator=[string]$h[0].VMCreatorId;Ports=@($h[0].LocalPorts);"
        " Remote=@($h[0].RemoteAddresses)};"
        "};"
        "$old=@(Get-NetFirewallHyperVRule -Name '" + LEGACY_WRONG_RULE + "' -ErrorAction SilentlyContinue);"
        "if ($old.Count -gt 1) { throw 'Ambiguous legacy WEAVE Hyper-V firewall rule' };"
        "if ($old.Count -eq 1) {"
        " $data.orphan=@{Direction=[string]$old[0].Direction;Action=[string]$old[0].Action;"
        " Enabled=[string]$old[0].Enabled;Protocol=[string]$old[0].Protocol;"
        " Creator=[string]$old[0].VMCreatorId;Ports=@($old[0].LocalPorts);"
        " Remote=@($old[0].RemoteAddresses)};"
        "};"
        "[Console]::Out.Write((ConvertTo-Json -InputObject $data -Compress -Depth 6))"
    )
    try:
        data = json.loads(lan._powershell(script, context="Inspect WEAVE mirrored firewall ownership"))
        if not isinstance(data, dict) or "windows" not in data or "hyperv" not in data:
            raise ValueError("Missing firewall rule metadata")
        return data
    except (ValueError, TypeError) as exc:
        raise MirroredFirewallError("Could not inspect mirrored firewall ownership safely.") from exc


def _values(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(item) for item in value]


def _network_equal(values, subnet: str, *, legacy_any: bool = False) -> bool:
    items = _values(values)
    if legacy_any and items == ["Any"]:
        return True
    if len(items) != 1:
        return False
    try:
        return ipaddress.IPv4Network(items[0], strict=True) == ipaddress.IPv4Network(subnet)
    except ValueError:
        return False


def _validate_windows(rule: dict | None, ip: str, subnet: str, alias: str | None) -> None:
    if rule is None:
        return
    if not isinstance(rule, dict):
        raise MirroredFirewallError("Invalid WEAVE Windows firewall ownership record.")
    profiles = {p.strip().lower() for p in str(rule.get("Profile", "")).split(",")}
    interfaces = _values(rule.get("Interface"))
    if not (rule.get("Direction", "").lower() == "inbound"
            and rule.get("Action", "").lower() == "allow"
            and rule.get("Enabled", "").lower() == "true"
            and str(rule.get("Protocol", "")).lower() in ("tcp", "6")
            and set(_values(rule.get("Ports"))) in ({"80"}, set(PORTS))
            and _values(rule.get("Local")) == [ip]
            and _network_equal(rule.get("Remote"), subnet)
            and bool(profiles) and profiles <= {"private", "domain"}
            and (not alias or interfaces in ([], ["Any"], [alias]))):
        raise MirroredFirewallError("WEAVE Windows mirrored rule was modified or has an unsafe scope; manual inspection required.")


def _validate_hyperv(rule: dict | None, subnet: str) -> bool:
    """Legacy WEAVE Hyper-V rule allowed any remote IP; narrow it in place."""
    if rule is None:
        return False
    if not isinstance(rule, dict):
        raise MirroredFirewallError("Invalid WEAVE Hyper-V firewall ownership record.")
    if not (str(rule.get("Creator", "")).casefold() == WSL_GUID.casefold()
            and str(rule.get("Direction", "")).lower() == "inbound"
            and str(rule.get("Action", "")).lower() == "allow"
            and str(rule.get("Enabled", "")).lower() == "true"
            and str(rule.get("Protocol", "")).lower() in ("tcp", "6")
            and set(_values(rule.get("Ports"))) in ({"80"}, set(PORTS))):
        raise MirroredFirewallError("WEAVE Hyper-V mirrored rule was modified; refusing to overwrite it.")
    if _network_equal(rule.get("Remote"), subnet):
        return False
    if _network_equal(rule.get("Remote"), subnet, legacy_any=True):
        return True
    raise MirroredFirewallError("Existing WEAVE Hyper-V rule has an unexpected remote scope.")


def _validate_old_orphan(rule: dict | None, subnet: str) -> None:
    """Identify a narrowly scoped rule written by the short-lived wrong-GUID release."""
    if rule is None:
        return
    if (not isinstance(rule, dict)
            or str(rule.get("Creator", "")).casefold() != LEGACY_WRONG_GUID.casefold()
            or str(rule.get("Direction", "")).lower() != "inbound"
            or str(rule.get("Action", "")).lower() != "allow"
            or str(rule.get("Enabled", "")).lower() != "true"
            or str(rule.get("Protocol", "")).lower() not in ("tcp", "6")
            or set(_values(rule.get("Ports"))) not in ({"80"}, set(PORTS))
            or not _network_equal(rule.get("Remote"), subnet)):
        raise MirroredFirewallError("Unexpected legacy WEAVE Hyper-V rule; review it before migration.")


def verify(ip: str, subnet: str, *, alias: str | None = None) -> dict:
    """Fail closed when an existing rule is not the expected WEAVE-owned rule."""
    ip = lan._private_address(ip)
    subnet = lan._private_subnet(subnet, ip)
    snapshot = _snapshot()
    _validate_windows(snapshot["windows"], ip, subnet, alias)
    _validate_old_orphan(snapshot.get("orphan"), subnet)
    snapshot["legacy_hyperv"] = _validate_hyperv(snapshot["hyperv"], subnet)
    snapshot["upgrade_windows_ports"] = bool(snapshot["windows"] and set(_values(snapshot["windows"]["Ports"])) != set(PORTS))
    snapshot["upgrade_hyperv_ports"] = bool(snapshot["hyperv"] and set(_values(snapshot["hyperv"]["Ports"])) != set(PORTS))
    return snapshot


def configure(stack, state: dict) -> None:
    """Idempotently repair missing rules; narrow legacy Hyper-V ingress."""
    ip, subnet, alias = _approved(stack, state)
    before = verify(ip, subnet, alias=alias)
    if before["hyperv"] is None:
        lan._powershell(
            "New-NetFirewallHyperVRule -Name '" + HYPERV_RULE
            + "' -DisplayName 'WEAVE CBT Mirrored School LAN' -Direction Inbound "
            "-Action Allow -Enabled True -VMCreatorId '" + WSL_GUID
            + "' -Protocol TCP -LocalPorts 80,443 -RemoteAddresses "
            + _quote(subnet) + " -ErrorAction Stop | Out-Null",
            context="Create restricted WEAVE Hyper-V firewall rule",
        )
    elif before["legacy_hyperv"]:
        # Only narrow the exact legacy rule which WEAVE's mode switch created.
        lan._powershell(
            "Set-NetFirewallHyperVRule -Name '" + HYPERV_RULE
            + "' -RemoteAddresses " + _quote(subnet) + " -ErrorAction Stop | Out-Null",
            context="Restrict legacy WEAVE Hyper-V firewall scope",
        )
    if before["hyperv"] is not None and before["upgrade_hyperv_ports"]:
        lan._powershell(
            "Set-NetFirewallHyperVRule -Name '" + HYPERV_RULE
            + "' -LocalPorts 80,443 -ErrorAction Stop | Out-Null",
            context="Update owned WEAVE Hyper-V TCP ports",
        )
    if before["windows"] is not None and before["upgrade_windows_ports"]:
        lan._powershell(
            "Get-NetFirewallRule -Name '" + WINDOWS_RULE
            + "' -ErrorAction Stop | Get-NetFirewallPortFilter | "
            "Set-NetFirewallPortFilter -LocalPort 80,443 -ErrorAction Stop | Out-Null",
            context="Update owned WEAVE Windows TCP ports",
        )
    if before["windows"] is None:
        lan._powershell(
            "New-NetFirewallRule -Name '" + WINDOWS_RULE
            + "' -DisplayName 'WEAVE CBT Mirrored School LAN' "
            "-Direction Inbound -Action Allow -Protocol TCP -LocalPort 80,443 "
            "-LocalAddress " + _quote(ip) + " -RemoteAddress " + _quote(subnet)
            + " -InterfaceAlias " + _quote(alias)
            + " -Profile Private,Domain -Enabled True -ErrorAction Stop | Out-Null",
            context="Create restricted WEAVE Windows mirrored firewall rule",
        )
    after = verify(ip, subnet, alias=alias)
    if before.get("orphan") is not None and after["windows"] and after["hyperv"] and not after["legacy_hyperv"]:
        lan._powershell(
            "Remove-NetFirewallHyperVRule -Name '" + LEGACY_WRONG_RULE + "' -ErrorAction Stop",
            context="Remove legacy WEAVE rule with incorrect WSL creator",
        )
        after = verify(ip, subnet, alias=alias)
    if (after.get("orphan") is not None or after["windows"] is None or after["hyperv"] is None or after["legacy_hyperv"]
            or after["upgrade_windows_ports"] or after["upgrade_hyperv_ports"]):
        raise MirroredFirewallError("WEAVE mirrored firewall validation failed after reconciliation.")


def remove(ip: str, subnet: str) -> None:
    """Delete only exact, ownership-validated WEAVE rules; safe when absent."""
    current = verify(ip, subnet)
    if current.get("orphan") is not None:
        lan._powershell(
            "Remove-NetFirewallHyperVRule -Name '" + LEGACY_WRONG_RULE + "' -ErrorAction Stop",
            context="Remove owned legacy WEAVE Hyper-V rule",
        )
    if current["hyperv"] is not None:
        lan._powershell(
            "Remove-NetFirewallHyperVRule -Name '" + HYPERV_RULE + "' -ErrorAction Stop",
            context="Remove owned WEAVE Hyper-V firewall rule",
        )
    if current["windows"] is not None:
        lan._powershell(
            "Remove-NetFirewallRule -Name '" + WINDOWS_RULE + "' -ErrorAction Stop",
            context="Remove owned WEAVE mirrored Windows firewall rule",
        )
    after = _snapshot()
    if after["hyperv"] is not None or after["windows"] is not None or after.get("orphan") is not None:
        raise MirroredFirewallError("WEAVE mirrored firewall rules remain after removal.")
