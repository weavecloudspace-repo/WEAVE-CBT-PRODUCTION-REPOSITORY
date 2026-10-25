"""Guarded WSL networking mode migration for a dedicated school server.

Mirrored mode is global to the Windows user's WSL distributions. Never switch
automatically on login or during an exam. Preserve previous .wslconfig bytes,
remove only WEAVE-owned NAT rules, and roll back on failed verification.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import typer

from weave_cli.commands._shared import get_stack, error, success, info, warning
from weave_cli.commands import lan, lan_tls
from weave_cli.networking.state import load_or_import, save
from weave_cli.networking.deployment import _atomic_bytes, _atomic_json

app = typer.Typer(help="Inspect or change WSL networking mode during maintenance.")
OWNER = "wsl-network-owner.json"
HYPERV_RULE = "WEAVE-CBT-MIRRORED"
WINDOWS_RULE = "WEAVE-CBT-MIRRORED-LAN"
GUID = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"


class ModeError(RuntimeError):
    pass


def edit_config(original: str, requested: str) -> str:
    """Preserve unrelated .wslconfig settings and require one unambiguous section."""
    if requested not in {"nat", "mirrored"}:
        raise ModeError("Invalid WSL networking mode.")
    sections = list(re.finditer(r"(?im)^\s*\[wsl2\]\s*$", original))
    if len(sections) > 1:
        raise ModeError("Duplicate [wsl2] sections in .wslconfig.")
    if not sections:
        return original.rstrip("\r\n") + "\n[wsl2]\nnetworkingMode=" + requested + "\n"
    start = sections[0].end()
    next_section = re.search(r"(?m)^\s*\[[^\]]+\]\s*$", original[start:])
    end = start + next_section.start() if next_section else len(original)
    before, section, after = original[:start], original[start:end], original[end:]
    matches = re.findall(r"(?im)^\s*networkingMode\s*=", section)
    if len(matches) > 1:
        raise ModeError("Duplicate networkingMode settings in .wslconfig.")
    if matches:
        section = re.sub(
            r"(?im)^(\s*networkingMode\s*=\s*)[^\r\n]*",
            lambda match: match.group(1) + requested, section, count=1,
        )
    else:
        section = section.rstrip("\r\n") + "\nnetworkingMode=" + requested + "\n"
    return before + section + after


def _config() -> Path:
    profile = os.environ.get("USERPROFILE")
    if not profile:
        raise ModeError("Windows installation-owner profile is unavailable.")
    return Path(profile) / ".wslconfig"


def _run(command: list[str]) -> None:
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=180, check=False
    )
    if result.returncode:
        raise ModeError("Windows/WSL operation failed: " + (result.stderr or "")[:500])


def _wsl_supported() -> bool:
    return (sys.platform == "win32"
            and sys.getwindowsversion().build >= 22621)


def _socket_open(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=4):
            return True
    except OSError:
        return False


def _mirror_rules(ip: str, subnet: str, *, remove: bool = False) -> None:
    ipq, netq = lan._private_address(ip), lan._private_subnet(subnet, ip)
    if remove:
        for rule in (WINDOWS_RULE,):
            lan._powershell(
                f"Get-NetFirewallRule -Name '{rule}' -ErrorAction SilentlyContinue | Remove-NetFirewallRule",
                context="Remove WEAVE mirrored firewall",
            )
        lan._powershell(
            f"Get-NetFirewallHyperVRule -Name '{HYPERV_RULE}' -ErrorAction SilentlyContinue | Remove-NetFirewallHyperVRule",
            context="Remove WEAVE Hyper-V firewall",
        )
    else:
        lan._powershell(
            "$ErrorActionPreference='Stop';"
            f"if(Get-NetFirewallRule -Name '{WINDOWS_RULE}' -ErrorAction SilentlyContinue) {{ throw 'Mirrored firewall rule already exists' }};"
            f"New-NetFirewallRule -Name '{WINDOWS_RULE}' -DisplayName '{WINDOWS_RULE}' "
            f"-Direction Inbound -Action Allow -Protocol TCP -LocalPort 80,443 "
            f"-LocalAddress '{ipq}' -RemoteAddress '{netq}' -Profile Private | Out-Null",
            context="Configure scoped mirrored LAN firewall",
        )
        lan._powershell(
            "$ErrorActionPreference='Stop';"
            f"if(Get-NetFirewallHyperVRule -Name '{HYPERV_RULE}' -ErrorAction SilentlyContinue) {{ throw 'Hyper-V rule already exists' }};"
            f"New-NetFirewallHyperVRule -Name '{HYPERV_RULE}' -DisplayName '{HYPERV_RULE}' "
            f"-Direction Inbound -VMCreatorId '{GUID}' -Protocol TCP -LocalPorts 80,443 | Out-Null",
            context="Configure scoped WSL Hyper-V ports",
        )


def _restart_wsl(stack) -> None:
    _run(["wsl.exe", "--shutdown"])
    stack.platform.start_docker_engine()
    stack.compose.start()


@app.command("status")
def mode_status() -> None:
    try:
        stack = get_stack()
        state = load_or_import(stack.installation.data_directory,
                               runtime_type=stack.installation.runtime_type)
        typer.echo(json.dumps({
            "active": state["transport"],
            "auto_switch": False,
            "mirrored_supported_by_windows": _wsl_supported(),
            "school_ip": state["address"],
        }, indent=2))
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("plan")
def mode_plan(preferred: str = typer.Option("auto", "--preferred")) -> None:
    if preferred not in {"auto", "nat", "mirrored"}:
        raise typer.BadParameter("Choose auto, nat or mirrored.")
    try:
        stack = get_stack()
        state = load_or_import(stack.installation.data_directory,
                               runtime_type=stack.installation.runtime_type)
        typer.echo(json.dumps({
            "requested": preferred,
            "selected": ("mirrored" if preferred == "auto" and _wsl_supported() else
                         "nat" if preferred == "auto" else preferred),
            "current": state["transport"],
            "requires_wsl_shutdown": preferred != state["transport"],
            "requires_maintenance": True,
            "requires_external_student_test": True,
            "note": "Docker port publishing and WSL firewall must pass live validation.",
        }, indent=2))
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("set")
def mode_set(
    target: str = typer.Argument(...),
    maintenance: bool = typer.Option(False, "--maintenance"),
    yes: bool = typer.Option(False, "--yes"),
    client_verified: bool = typer.Option(False, "--client-verified"),
) -> None:
    """Change WSL mode with backups; never a background/startup operation."""
    try:
        stack = get_stack()
        if sys.platform != "win32" or stack.installation.runtime_type != "wsl2":
            raise ModeError("WSL mode management requires a Windows WEAVE CBT host.")
        if not stack.platform.is_admin():
            raise ModeError("Run an elevated Administrator terminal.")
        if target == "auto":
            target = "mirrored" if _wsl_supported() else "nat"
        if target not in {"nat", "mirrored"}:
            raise ModeError("Choose nat, mirrored or auto.")
        if target == "mirrored" and not _wsl_supported():
            raise ModeError("Mirrored mode requires supported Windows 11 22H2+ and recent WSL.")
        state = load_or_import(stack.installation.data_directory, runtime_type="wsl2")
        if state["transport"] == target:
            success("WSL network mode is already " + target)
            return
        if not state["address"] or not state["subnet"] or not state["interface_guid"]:
            raise ModeError("Select the preferred school interface before changing WSL mode.")
        if not maintenance:
            raise ModeError("Use --maintenance after confirming there are no active examinations.")
        if not yes and not typer.confirm(
            "Changing WSL mode interrupts all user-owned WSL distributions. Continue?",
            default=False,
        ):
            return
        wslconfig = _config()
        if wslconfig.is_symlink() or (wslconfig.exists() and not wslconfig.is_file()):
            raise ModeError("Unexpected .wslconfig path.")
        previous = wslconfig.read_bytes() if wslconfig.exists() else None
        if previous and len(previous) > 512 * 1024:
            raise ModeError("Unexpectedly large .wslconfig; inspect manually.")
        original_text = previous.decode("utf-8-sig") if previous else ""
        import base64
        owner = stack.installation.data_directory / OWNER
        previous_owner = json.loads(owner.read_text(encoding="utf-8")) if owner.exists() else None
        old_nat = (stack.installation.data_directory / "lan.json").is_file()
        old_https = (stack.installation.data_directory / "tls-lan.json").is_file()
        if previous_owner:
            if target != "nat" or previous_owner.get("target") != "mirrored":
                raise ModeError("An owned mirrored WSL change is already recorded.")
            owned_original = base64.b64decode(previous_owner["original"], validate=True)
            original_owned = owned_original.decode("utf-8-sig")
            if original_text != edit_config(original_owned, "mirrored"):
                raise ModeError("Another program modified .wslconfig; refusing to overwrite it.")
            updated = original_owned if previous_owner["original_exists"] else ""
            old_nat = bool(previous_owner["legacy_nat"])
            old_https = bool(previous_owner["legacy_https"])
        else:
            updated = edit_config(original_text, target)
            _atomic_json(owner, {
                "original": base64.b64encode(previous or b"").decode("ascii"),
                "original_exists": previous is not None,
                "target": target,
                "legacy_nat": old_nat,
                "legacy_https": old_https,
            })
        try:
            if target == "mirrored":
                if old_nat:
                    lan.configure(stack.installation.data_directory, remove=True)
                _mirror_rules(state["address"], state["subnet"])
            _atomic_bytes(wslconfig, updated.encode("utf-8"))
            _restart_wsl(stack)
            if target == "nat":
                _mirror_rules(state["address"], state["subnet"], remove=True)
                lan.configure(
                    stack.installation.data_directory,
                    listen_address=state["address"], client_subnet=state["subnet"],
                )
                if old_https or (stack.installation.data_directory / "tls.enabled").exists():
                    lan_tls.reconcile(stack.installation.data_directory)
            if not all(_socket_open(state["address"], port) for port in (80, 443)):
                raise ModeError("School IP ports 80/443 did not pass host verification.")
            if not client_verified and not typer.confirm(
                "Did a separate school computer successfully open the HTTPS student URL?",
                default=False,
            ):
                raise ModeError("School-device verification was not confirmed.")
            state["transport"] = target
            save(stack.installation.data_directory, state)
            if target == "nat":
                owner.unlink(missing_ok=True)
            success("WSL network mode changed to " + target)
            warning("The previous .wslconfig is backed up in WEAVE metadata for explicit restoration.")
        except Exception:
            try:
                if previous is not None:
                    _atomic_bytes(wslconfig, previous)
                else:
                    wslconfig.unlink(missing_ok=True)
                _restart_wsl(stack)
                if target == "mirrored":
                    _mirror_rules(state["address"], state["subnet"], remove=True)
                    if old_nat:
                        lan.configure(
                            stack.installation.data_directory,
                            listen_address=state["address"], client_subnet=state["subnet"],
                        )
                        if old_https:
                            lan_tls.reconcile(stack.installation.data_directory)
            except Exception as rollback_error:
                raise ModeError(
                    "WSL migration failed and rollback needs manual repair: " + str(rollback_error)
                ) from rollback_error
            owner.unlink(missing_ok=True)
            raise
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(network_app: typer.Typer) -> None:
    network_app.add_typer(app, name="mode")
