"""Shared, ownership-checked host cleanup for destructive CBT lifecycle operations.

Both purge uninstall and purge reinstall use the same path. Never infer that
a host portproxy or DNS service belongs to CBT merely from its port/name.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from weave_cli.commands import lan, lan_tls
from weave_cli.commands.network_dns import remove_if_configured


@dataclass(frozen=True)
class HostSnapshot:
    addresses: tuple[str, ...]
    runtime_type: str


def _tls_address(path: Path) -> str:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        address = lan._private_address(record["listen_address"])
        lan._private_subnet(record["client_subnet"], address)
        lan._private_address(record["wsl_address"])
        return address
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise lan.LanError("Unrecognized HTTPS ownership record; inspect tls-lan.json.") from exc


def _windows_unowned_resources(data: Path, addresses: set[str]) -> None:
    """Refuse unidentified resources instead of destroying another service.

    Check active private adapters as well as saved listeners. This catches the
    common case where LAN/HTTPS state was lost but forwarding still targets the
    currently running WeaveCBT WSL distribution. Other mappings are untouched.
    """
    from weave_cli.commands import network, network_dns

    active = [
        row["address"] for row in network.inventory()
        if row.get("private") and row.get("category") in ("Private", "DomainAuthenticated")
    ]
    addresses.update(active)
    try:
        wsl_address = lan._wsl_address()
    except lan.LanError:
        wsl_address = None

    http_owned = (data / "lan.json").is_file()
    tls_owned = (data / "tls-lan.json").is_file()
    for address in sorted(addresses):
        if not http_owned:
            dest = lan._mapped_destination(address)
            if dest and wsl_address and dest == f"{wsl_address}/80":
                raise lan.LanError(
                    f"Unowned TCP/80 forwarding at {address} points to WeaveCBT WSL. "
                    "Inspect 'netsh interface portproxy show v4tov4' and remove it manually if obsolete."
                )
        if not tls_owned:
            dest = lan_tls._destination(address)
            if dest and wsl_address and dest == f"{wsl_address}/443":
                raise lan.LanError(
                    f"Unowned TCP/443 forwarding at {address} points to WeaveCBT WSL. "
                    "Inspect 'netsh interface portproxy show v4tov4' and remove it manually if obsolete."
                )
    if not http_owned and lan._firewall_exists():
        raise lan.LanError("WEAVE TCP/80 firewall rule exists without LAN ownership state; inspect it manually.")
    if not tls_owned and lan_tls._firewall_exists():
        raise lan.LanError("WEAVE TCP/443 firewall rule exists without TLS ownership state; inspect it manually.")

    # Do not remove a CoreDNS service without an owned configuration record.
    if not (data / "dns" / "managed.json").is_file() and network_dns._service_exists():
        raise lan.LanError(
            "CoreDNS Windows service exists without WEAVE ownership metadata. "
            "Inspect the service before retrying purge."
        )


def preflight(stack) -> HostSnapshot:
    """Fail before destroying exam data when host ownership is ambiguous."""
    data = stack.installation.data_directory
    runtime_type = stack.installation.runtime_type
    addresses: set[str] = set()
    if runtime_type == "wsl2" and sys.platform == "win32":
        state = lan._read_state(data)
        if state:
            addresses.add(state["listen_address"])
        if (data / "tls-lan.json").exists():
            addresses.add(_tls_address(data / "tls-lan.json"))
        _windows_unowned_resources(data, addresses)
    else:
        # Check configured native DNS ownership before deleting Docker data.
        from weave_cli.commands import network_dns_linux
        if runtime_type == "native" and sys.platform.startswith("linux"):
            network_dns_linux._snapshot(stack)
    return HostSnapshot(addresses=tuple(sorted(addresses)), runtime_type=runtime_type)


def cleanup_host(stack, *, purge_files: bool = True) -> None:
    """Unregister DNS, then HTTPS, then HTTP; leave other services untouched."""
    data = stack.installation.data_directory
    remove_if_configured(stack, purge_files=purge_files)
    if stack.installation.runtime_type == "wsl2":
        # HTTPS removal must work even when lan.json is missing.
        if (data / "tls-lan.json").exists():
            lan_tls.reconcile(data, remove=True)
        if (data / "lan.json").exists():
            lan.configure(data, remove=True)


def verify_host(stack, snapshot: HostSnapshot) -> None:
    """Do not declare purge successful while a verified host artifact remains."""
    data = stack.installation.data_directory
    for relative in ("lan.json", "tls-lan.json", "dns/managed.json"):
        if (data / relative).exists():
            raise lan.LanError(f"WEAVE host cleanup is incomplete: {relative} remains.")
    if snapshot.runtime_type == "wsl2" and sys.platform == "win32":
        from weave_cli.commands import network_dns
        for address in snapshot.addresses:
            if lan._mapped_destination(address) is not None:
                raise lan.LanError(f"TCP/80 forwarding remains at {address}; inspect ownership.")
            if lan_tls._destination(address) is not None:
                raise lan.LanError(f"TCP/443 forwarding remains at {address}; inspect ownership.")
        if lan._firewall_exists() or lan_tls._firewall_exists():
            raise lan.LanError("WEAVE HTTP/HTTPS firewall rule remains after cleanup.")
        if network_dns._service_exists():
            raise lan.LanError("CoreDNS service remains after WEAVE cleanup.")
    elif snapshot.runtime_type == "native" and sys.platform.startswith("linux"):
        from weave_cli.commands import network_dns_linux
        if network_dns_linux._snapshot(stack)["configured"]:
            raise lan.LanError("WEAVE CoreDNS systemd service remains after cleanup.")


def clear_active_config(data: Path, install: Path) -> None:
    """Remove only known active WEAVE files, never directories or unknown files.

    Caller must first destroy Compose, verify Docker/host cleanup, unregister
    scheduled persistence and delete the installation registration.
    """
    targets = (
        data / "tls.enabled",
        data / "runtime.env",
        data / "lan.json",
        data / "tls-lan.json",
        install / "compose.yaml",
        install / "nginx" / "nginx.conf",
        install / "nginx" / "reload-watch.sh",
        install / "certificates" / "hooks.py",
    )
    for path in targets:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise lan.LanError(f"Unsafe installation artifact: {path}")
    for path in targets:
        path.unlink(missing_ok=True)
