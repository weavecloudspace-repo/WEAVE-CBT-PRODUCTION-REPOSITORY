"""Opt-in CoreDNS for WEAVE school hosts on Windows and native Linux."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import typer

from weave_cli.commands._shared import get_stack, banner, error, info, success, warning
from weave_cli.commands import lan

app = typer.Typer(help="Manage the optional local CoreDNS service.")
SERVICE = "CoreDNS"
FIREWALL = ("WEAVE-CBT-DNS-UDP53", "WEAVE-CBT-DNS-TCP53")
VERSION = "1.14.7"
ZIP_SHA256 = "6b718a5ed57d7034b1e4c3df500121307830da291d15cf8387f41c297c6fdd56"
ARCHIVE_URL = (
    f"https://github.com/coredns/coredns/releases/download/v{VERSION}/"
    f"coredns_{VERSION}_windows_amd64.zip"
)
HOST_RE = re.compile(r"[a-z0-9-]+\.[a-z0-9-]+\.cbt(?:-staging)?\.weavecloudspace\.com\Z")


class DNSError(RuntimeError):
    pass


def _paths(stack) -> tuple[Path, Path, Path, Path]:
    root = stack.installation.data_directory / "dns"
    return (root, root / "Corefile", root / "records.hosts", root / "managed.json")


def _service_exists() -> bool:
    return lan._powershell(
        "$s=Get-Service -Name 'CoreDNS' -ErrorAction SilentlyContinue; "
        "if ($null -eq $s) { 'false' } else { 'true' }",
        context="Inspect local DNS service",
    ).strip().lower() == "true"


def _ensure_binary(destination: Path) -> None:
    if destination.is_file():
        raise DNSError("An unverified CoreDNS executable is already present; inspect it before setup.")
    request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "WEAVE-CBT-DNS/1"})
    try:
        with urllib.request.urlopen(request, timeout=75) as response:
            if response.status != 200:
                raise DNSError("CoreDNS download did not succeed.")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as f:
                archive_path = Path(f.name)
                size, digest = 0, hashlib.sha256()
                while True:
                    block = response.read(1024 * 512)
                    if not block:
                        break
                    size += len(block)
                    if size > 70 * 1024 * 1024:
                        raise DNSError("CoreDNS archive is unexpectedly large.")
                    digest.update(block)
                    f.write(block)
        if digest.hexdigest() != ZIP_SHA256:
            raise DNSError("CoreDNS SHA-256 does not match the verified official release.")
        with zipfile.ZipFile(archive_path) as archive:
            entries = [name for name in archive.namelist() if name.replace("\\", "/") == "coredns.exe"]
            if len(entries) != 1:
                raise DNSError("Official CoreDNS archive does not contain the expected executable.")
            payload = archive.read(entries[0])
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".new")
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    except (OSError, TimeoutError, zipfile.BadZipFile) as exc:
        raise DNSError("Unable to download or verify the official CoreDNS release.") from exc
    finally:
        if "archive_path" in locals():
            archive_path.unlink(missing_ok=True)


def _write_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8",
                                      prefix=".weave-dns-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _get_ip_and_hostname(stack) -> tuple[str, str, str]:
    if stack.installation.runtime_type != "wsl2" or sys.platform != "win32":
        raise DNSError("WEAVE-managed CoreDNS setup currently supports Windows WSL2 only.")
    if not (stack.installation.data_directory / "tls.enabled").is_file():
        raise DNSError("Pair the CBT server and activate HTTPS before setting up school DNS.")
    mapped = lan._read_state(stack.installation.data_directory)
    if mapped is None:
        raise DNSError("Configure the trusted school network first: weave network setup.")
    from weave_cli.commands.network import _https_hostname
    hostname = _https_hostname(stack)
    if not hostname or not HOST_RE.fullmatch(hostname):
        raise DNSError("Cannot verify the HTTPS hostname assigned during pairing.")
    return hostname, mapped["listen_address"], mapped["client_subnet"]


def _read_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        block = sock.recv(length - len(chunks))
        if not block:
            raise OSError("DNS server closed the connection before replying.")
        chunks.extend(block)
    return bytes(chunks)


def _dns_answer(address: str, name: str, *, timeout: float = 5.0, tcp: bool = False) -> bool:
    """Query the configured resolver directly; never use the Windows hosts file."""
    query_id = 0x493B
    qname = b"".join(bytes([len(chunk)]) + chunk.encode("ascii") for chunk in name.split(".")) + b"\0"
    packet = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", 1, 1)
    try:
        if tcp:
            with socket.create_connection((address, 53), timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(struct.pack("!H", len(packet)) + packet)
                size = _read_exact(sock, 2)
                reply = _read_exact(sock, struct.unpack("!H", size)[0])
            source_address = address
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(timeout)
                sock.sendto(packet, (address, 53))
                reply, source = sock.recvfrom(4096)
            source_address = source[0]
        if source_address != address or len(reply) < 12 or reply[:2] != struct.pack("!H", query_id):
            return False
        if reply[3] & 0x0F or int.from_bytes(reply[6:8], "big") < 1:
            return False
        # In a standard A answer, an IPv4 value occurs in an A RR with 4-byte rdata.
        cursor = 12
        for _ in range(2):
            while cursor < len(reply) and reply[cursor]:
                if reply[cursor] & 0xC0 == 0xC0:
                    cursor += 2
                    break
                cursor += 1 + reply[cursor]
            else:
                cursor += 1
            if _ == 0:
                cursor += 4
                continue
            if cursor + 10 > len(reply):
                return False
            kind, _, _, size = struct.unpack("!HHIH", reply[cursor:cursor + 10])
            cursor += 10
            return kind == 1 and size == 4 and reply[cursor:cursor + 4] == ipaddress.IPv4Address(address).packed
        return False
    except (OSError, ValueError, IndexError):
        return False


def _firewall_setup(address: str, subnet: str) -> None:
    for protocol, name in (("UDP", FIREWALL[0]), ("TCP", FIREWALL[1])):
        # Existing rules with our names must not be silently overwritten.
        lan._powershell(
            "$r=Get-NetFirewallRule -Name '" + name + "' -ErrorAction SilentlyContinue; "
            "if ($r) { throw 'A DNS firewall rule already exists; inspect ownership first' }; "
            "New-NetFirewallRule -Name '" + name + "' -DisplayName 'WEAVE CBT school DNS' "
            "-Enabled True -Direction Inbound -Action Allow -Profile Private,Domain "
            "-Protocol " + protocol + " -LocalPort 53 -LocalAddress '" + address +
            "' -RemoteAddress '" + subnet + "' | Out-Null",
            context="Configure school DNS firewall",
        )


def _service_action(*args: str) -> None:
    lan._run(["sc.exe", *args], context="WEAVE-owned CoreDNS service")


def _status(stack) -> dict:
    if stack.installation.runtime_type == "native" and sys.platform.startswith("linux"):
        from weave_cli.commands.network_dns_linux import _snapshot
        return _snapshot(stack)
    root, _, _, state_file = _paths(stack)
    try:
        saved = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else None
    except (ValueError, OSError):
        raise DNSError("Local DNS ownership state is unreadable; do not overwrite unknown services.")
    service = _service_exists() if sys.platform == "win32" else False
    return {"configured": bool(saved), "service_registered": service,
            "hostname": saved.get("hostname") if saved else None,
            "address": saved.get("address") if saved else None,
            "router_verified": False}


def setup(stack, *, interface: str | None = None) -> dict:
    if stack.installation.runtime_type == "native" and sys.platform.startswith("linux"):
        from weave_cli.commands.network_dns_linux import setup_linux
        return setup_linux(stack, interface=interface)
    if interface is not None:
        raise DNSError("--interface is used only for native Linux CoreDNS setup.")
    if not stack.platform.is_admin():
        raise DNSError("Run from Administrator PowerShell.")
    hostname, address, subnet = _get_ip_and_hostname(stack)
    root, corefile, records, state_file = _paths(stack)
    state = _status(stack)
    if state["service_registered"] and not state["configured"]:
        raise DNSError("A CoreDNS service already exists without WEAVE ownership metadata.")
    if state["configured"] and (
        state["address"] != address or state["hostname"] != hostname
    ):
        raise DNSError("DNS identity changed. Run weave network dns remove before reconfiguring.")
    if state["configured"]:
        if not _dns_answer(address, hostname):
            try:
                _service_action("start", SERVICE)
            except lan.LanError:
                pass
        if not _dns_answer(address, hostname):
            raise DNSError("CoreDNS is configured but not answering correctly.")
        return _status(stack)
    # Do not make external DNS a prerequisite for ordinary WEAVE restart.
    executable = stack.installation.install_directory / "coredns.exe"
    _ensure_binary(executable)
    if not root.exists():
        root.mkdir(parents=True)
    # Windows CoreDNS runs as LocalSystem. Keep configuration admin/SYSTEM-only.
    lan._run(["icacls.exe", str(root), "/inheritance:r",
              "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
             context="Secure WEAVE DNS configuration")
    _write_atomic(records, f"{address} {hostname}\n")
    _write_atomic(corefile, (
        ".:53 {\n"
        f"    bind 127.0.0.1 {address}\n"
        "    errors\n    reload\n"
        f"    hosts {records.as_posix()} {{\n"
        "        ttl 60\n        fallthrough\n    }\n"
        "    forward . 1.1.1.1 8.8.8.8\n"
        "    cache 30\n}\n"
    ))
    # Check both names before changing any rules: WEAVE must not overwrite or
    # remove unrelated rules, even if they happen to use the same names.
    for rule in FIREWALL:
        present = lan._powershell(
            "$r=Get-NetFirewallRule -Name '" + rule + "' -ErrorAction SilentlyContinue; "
            "if ($r) { 'true' } else { 'false' }", context="Check WEAVE DNS firewall ownership"
        ).strip().lower() == "true"
        if present:
            raise DNSError("A DNS firewall rule already exists. Inspect it before setup.")
    created = False
    try:
        # CoreDNS 1.14.3+ has native Windows-service support.
        _service_action("create", SERVICE, "binPath=",
                        f'"{executable}" -conf "{corefile}" -windows-service',
                        "start=", "auto", "DisplayName=", "WEAVE CBT Local DNS")
        created = True
        _firewall_setup(address, subnet)
        _service_action("start", SERVICE)
        if not _dns_answer(address, hostname):
            raise DNSError("CoreDNS did not answer the assigned hostname on port 53.")
        _write_atomic(state_file, json.dumps(
            {"schema": 1, "hostname": hostname, "address": address, "subnet": subnet,
             "executable": str(executable)}, sort_keys=True))
        return _status(stack)
    except (OSError, lan.LanError, DNSError):
        if created:
            try:
                _service_action("stop", SERVICE)
            except lan.LanError:
                pass
            _service_action("delete", SERVICE)
        for rule in FIREWALL:
            lan._powershell("Remove-NetFirewallRule -Name '" + rule +
                            "' -ErrorAction SilentlyContinue", context="Rollback school DNS firewall")
        raise


def remove_if_configured(stack, *, purge_files: bool = False) -> None:
    """Remove the verified WEAVE DNS service; purge additionally clears its files.

    Normal removal preserves the executable/config for incident review. The
    opt-in DNS commands and future DNS setup remain available in both modes.
    """
    if stack.installation.runtime_type == "native" and sys.platform.startswith("linux"):
        from weave_cli.commands.network_dns_linux import remove_linux
        remove_linux(stack)
        return
    root, corefile, records, state_file = _paths(stack)
    if not state_file.exists():
        return
    state = _status(stack)
    if not state["configured"]:
        return
    installed = stack.installation.install_directory / "coredns.exe"
    if purge_files:
        try:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise DNSError("Unrecognized WEAVE DNS ownership record.") from exc
        if (saved.get("schema") != 1 or saved.get("executable") != str(installed)):
            raise DNSError("CoreDNS ownership record differs from the WEAVE installation.")
        for path in (installed, corefile, records, state_file):
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise DNSError(f"Unsafe WEAVE DNS artifact: {path}")
    if state["service_registered"]:
        try:
            _service_action("stop", SERVICE)
        except lan.LanError:
            pass
        _service_action("delete", SERVICE)
    for name in FIREWALL:
        lan._powershell("Remove-NetFirewallRule -Name '" + name +
                        "' -ErrorAction SilentlyContinue", context="Remove WEAVE DNS firewall")
    state_file.unlink(missing_ok=True)
    if purge_files:
        for path in (corefile, records, installed):
            path.unlink(missing_ok=True)
        if root.exists():
            try:
                root.rmdir()
            except OSError:
                # Unknown files may belong to an administrator: never remove
                # or recursively delete the directory.
                pass


def reconcile_if_configured(stack) -> None:
    """Do not alter CoreDNS or HTTPS if the school has never opted into DNS."""
    if stack.installation.runtime_type == "native" and sys.platform.startswith("linux"):
        from weave_cli.commands.network_dns_linux import reconcile_linux
        reconcile_linux(stack)
        return
    _, _, _, state_file = _paths(stack)
    if not state_file.exists():
        return
    expected, address, _ = _get_ip_and_hostname(stack)
    current = _status(stack)
    if current["hostname"] != expected or current["address"] != address:
        raise DNSError("The configured DNS identity differs from HTTPS. Reconfigure DNS before student access.")


@app.command("status")
def dns_status(json_output: bool = typer.Option(False, "--json")) -> None:
    try:
        state = _status(get_stack())
        if json_output:
            typer.echo(json.dumps(state, separators=(",", ":")))
            return
        banner("Local school DNS")
        if not state["configured"]:
            warning("CoreDNS is not configured. Use weave network dns setup after HTTPS.")
        else:
            info(f"Hostname: {state['hostname']}")
            info(f"DNS address for router DHCP: {state['address']}")
            info("Service registered: " + ("yes" if state["service_registered"] else "no"))
            warning("Router/client DNS has not been independently verified.")
    except (DNSError, OSError, lan.LanError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("setup")
def dns_setup(
    interface: str | None = typer.Option(None, "--interface", help="Linux: exact school Ethernet/Wi-Fi adapter name."),
) -> None:
    try:
        state = setup(get_stack(), interface=interface)
        banner("Local school DNS")
        success("CoreDNS is answering the paired hostname on the school server.")
        info(f"Configure the router DHCP DNS server as: {state['address']}")
        warning("Do not change the router until a second computer can query DNS over UDP and TCP 53.")
    except (DNSError, OSError, lan.LanError, RuntimeError, ValueError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("remove")
def dns_remove(yes: bool = typer.Option(False, "--yes")) -> None:
    try:
        stack = get_stack()
        if not stack.platform.is_admin():
            raise DNSError("Administrator permissions are required.")
        if not yes and not typer.confirm(
            "Have you restored the router's original DNS server first? Remove WEAVE DNS?", default=False
        ):
            return
        remove_if_configured(stack)
        success("WEAVE-owned DNS service removed. Router settings are unchanged.")
    except (DNSError, OSError, lan.LanError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(network_app: typer.Typer) -> None:
    network_app.add_typer(app, name="dns")
