"""Linux systemd integration for opt-in, school-scoped WEAVE CoreDNS.

Only WEAVE-owned files and a dedicated systemd unit are changed. DHCP/router,
existing resolvers, and host firewall policies remain administrator-controlled.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

from weave_cli.commands import network
from weave_cli.commands.network_dns import DNSError, VERSION, _dns_answer, _paths, _write_atomic

UNIT = "weave-cbt-coredns.service"
UNIT_FILE = Path("/etc/systemd/system") / UNIT
LINUX_SHA256 = "9a09356438c6d9591cb80011a2a7a52f87fc3a113f6690e41f243f98b98faac9"
LINUX_URL = (
    f"https://github.com/coredns/coredns/releases/download/v{VERSION}/"
    f"coredns_{VERSION}_linux_amd64.tgz"
)


def _systemctl(*args: str, check: bool = True) -> bool:
    try:
        result = subprocess.run(["systemctl", *args], capture_output=True, text=True,
                                timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DNSError("Cannot control the CoreDNS systemd service.") from exc
    if check and result.returncode:
        raise DNSError(f"systemctl {' '.join(args)} failed: {(result.stderr or result.stdout).strip()[:350]}")
    return result.returncode == 0


def _owned_unit(root: Path) -> bool:
    if UNIT_FILE.is_symlink() or not UNIT_FILE.is_file():
        return False
    try:
        content = UNIT_FILE.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        content.startswith("# WEAVE CBT managed CoreDNS service\n")
        and f"ExecStart={root / 'coredns'} -conf {root / 'Corefile'}" in content
    )


def _snapshot(stack) -> dict:
    root, _, _, marker = _paths(stack)
    if marker.is_symlink():
        raise DNSError("Unsafe CoreDNS ownership marker; inspect the installation.")
    try:
        state = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else None
    except (ValueError, OSError) as exc:
        raise DNSError("CoreDNS ownership marker is unreadable; inspect before proceeding.") from exc
    if state is not None and (
        not isinstance(state, dict) or state.get("platform") != "linux"
        or state.get("schema") != 1
    ):
        raise DNSError("Unknown local DNS ownership metadata.")
    installed = _owned_unit(root)
    if state and not installed:
        raise DNSError("Linux DNS metadata exists but the systemd unit does not match WEAVE ownership.")
    return {
        "configured": bool(state),
        "service_registered": installed,
        "service_running": installed and _systemctl("is-active", "--quiet", UNIT, check=False),
        "hostname": state.get("hostname") if state else None,
        "address": state.get("address") if state else None,
        "interface": state.get("interface") if state else None,
        "router_verified": False,
    }


def _identity(stack, interface: str | None) -> tuple[str, dict]:
    if stack.installation.runtime_type != "native":
        raise DNSError("Linux CoreDNS requires a native Linux WEAVE CBT installation.")
    if not (stack.installation.data_directory / "tls.enabled").is_file():
        raise DNSError("Pair WEAVE CBT and successfully activate HTTPS before CoreDNS setup.")
    from weave_cli.commands.network import _https_hostname
    from weave_cli.commands.network_dns import HOST_RE
    hostname = _https_hostname(stack)
    if not hostname or not HOST_RE.fullmatch(hostname):
        raise DNSError("The paired HTTPS hostname could not be verified.")
    adapters = network.inventory()
    if interface:
        try:
            selected = network._candidate(adapters, interface)
        except (ValueError, RuntimeError) as exc:
            raise DNSError(str(exc)) from exc
    else:
        selected = network.recommend(adapters)
    if not selected:
        raise DNSError("Cannot choose one school interface. Use --interface with a private school adapter from weave network status.")
    address = selected["address"]
    cidr = selected["network"]
    subnet = ipaddress.IPv4Network(cidr)
    if not subnet.prefixlen >= 24 or not ipaddress.IPv4Address(address) in subnet:
        raise DNSError("Only specific private school /24-or-narrower networks are supported.")
    return hostname, selected


def _check_dns_port(address: str) -> None:
    """Fail before installation if another resolver owns this school IP/port."""
    for socktype in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
        try:
            with socket.socket(socket.AF_INET, socktype) as sock:
                sock.bind((address, 53))
        except OSError as exc:
            raise DNSError(f"DNS port 53 is unavailable at {address}; inspect existing DNS services.") from exc


def _download_binary(destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise DNSError("An unmanaged CoreDNS executable already exists; refusing to overwrite it.")
    archive_path = None
    try:
        request = urllib.request.Request(LINUX_URL, headers={"User-Agent": "WEAVE-CBT-DNS/1"})
        with urllib.request.urlopen(request, timeout=75) as response:
            if response.status != 200:
                raise DNSError("The official CoreDNS Linux archive could not be downloaded.")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tgz") as file:
                archive_path = Path(file.name)
                digest = hashlib.sha256()
                count = 0
                while True:
                    part = response.read(512 * 1024)
                    if not part:
                        break
                    count += len(part)
                    if count > 70 * 1024 * 1024:
                        raise DNSError("CoreDNS archive exceeds the allowed size.")
                    digest.update(part)
                    file.write(part)
        if digest.hexdigest() != LINUX_SHA256:
            raise DNSError("CoreDNS Linux release failed SHA-256 verification.")
        with tarfile.open(archive_path, "r:gz") as tar:
            member = tar.getmember("coredns")
            if not member.isfile() or member.size > 100 * 1024 * 1024:
                raise DNSError("CoreDNS archive contains an unexpected binary.")
            stream = tar.extractfile(member)
            if stream is None:
                raise DNSError("CoreDNS executable is missing from the archive.")
            with stream:
                payload = stream.read(100 * 1024 * 1024 + 1)
        if len(payload) > 100 * 1024 * 1024:
            raise DNSError("CoreDNS executable exceeds the allowed size.")
        # Exclusive creation protects existing files; never extract arbitrary tar paths.
        with destination.open("xb") as executable:
            executable.write(payload)
            executable.flush()
            os.fsync(executable.fileno())
        destination.chmod(0o700)
    except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
        raise DNSError("Cannot safely download and install the CoreDNS executable.") from exc
    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)


def _unit_text(root: Path) -> str:
    return (
        "# WEAVE CBT managed CoreDNS service\n"
        "[Unit]\n"
        "Description=WEAVE CBT school-local CoreDNS resolver\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={root}\n"
        f"ExecStart={root / 'coredns'} -conf {root / 'Corefile'}\n"
        "Restart=on-failure\n"
        "RestartSec=3s\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n"
        "ProtectSystem=strict\n"
        "ProtectHome=true\n"
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n"
        "CapabilityBoundingSet=CAP_NET_BIND_SERVICE\n"
        "AmbientCapabilities=CAP_NET_BIND_SERVICE\n"
        "UMask=0077\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _verify_running(address: str, hostname: str) -> None:
    for _ in range(8):
        if _dns_answer(address, hostname) and _dns_answer(address, hostname, tcp=True):
            return
        time.sleep(0.4)
    raise DNSError("CoreDNS did not answer the paired hostname over both UDP and TCP port 53.")


def setup_linux(stack, *, interface: str | None = None) -> dict:
    if not stack.platform.is_admin():
        raise DNSError("Run Linux DNS setup with sudo/root.")
    hostname, adapter = _identity(stack, interface)
    address, subnet = adapter["address"], adapter["network"]
    root, corefile, records, marker = _paths(stack)
    state = _snapshot(stack)
    if UNIT_FILE.is_symlink() or (UNIT_FILE.exists() and not state["configured"]):
        raise DNSError("A CoreDNS systemd unit already exists without WEAVE ownership.")
    if state["configured"]:
        if (state["hostname"] != hostname or state["address"] != address
                or state["interface"] != adapter["name"]):
            raise DNSError("The paired hostname or server IP changed. Restore router DNS and run weave network dns remove before configuring again.")
        if not state["service_running"]:
            _systemctl("start", UNIT)
        _verify_running(address, hostname)
        return _snapshot(stack)

    _check_dns_port(address)
    if root.is_symlink() or corefile.exists() or records.exists() or marker.exists():
        raise DNSError("Existing unmanaged DNS configuration detected; refusing to overwrite it.")
    created_root = not root.exists()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if created_root:
        root.chmod(0o700)
    elif root.stat().st_uid != 0:
        raise DNSError("Existing local DNS directory is not root-owned.")
    binary = root / "coredns"
    _download_binary(binary)
    started = False
    try:
        _write_atomic(records, f"{address} {hostname}\n")
        _write_atomic(corefile,
            ".:53 {\n"
            f"    bind 127.0.0.1 {address}\n"
            "    errors\n"
            "    reload\n"
            f"    hosts {records} {{\n"
            "        ttl 60\n"
            "        fallthrough\n"
            "    }\n"
            "    forward . 1.1.1.1 8.8.8.8\n"
            "    cache 30\n"
            "}\n"
        )
        # /etc/systemd/system is owned by root; fail closed on foreign units.
        if UNIT_FILE.exists() or UNIT_FILE.is_symlink():
            raise DNSError("A CoreDNS systemd unit appeared while preparing setup.")
        with UNIT_FILE.open("x", encoding="utf-8") as unit:
            unit.write(_unit_text(root))
        UNIT_FILE.chmod(0o644)
        started = True
        _systemctl("daemon-reload")
        _systemctl("enable", "--now", UNIT)
        _verify_running(address, hostname)
        _write_atomic(marker, json.dumps({
            "schema": 1, "platform": "linux", "hostname": hostname,
            "address": address, "subnet": subnet, "interface": adapter["name"],
            "version": VERSION,
        }, sort_keys=True))
        return _snapshot(stack)
    except Exception:
        if started and _owned_unit(root):
            _systemctl("disable", "--now", UNIT, check=False)
            UNIT_FILE.unlink(missing_ok=True)
            _systemctl("daemon-reload", check=False)
        binary.unlink(missing_ok=True)
        records.unlink(missing_ok=True)
        corefile.unlink(missing_ok=True)
        raise


def remove_linux(stack) -> None:
    if not stack.platform.is_admin():
        raise DNSError("Administrator/root privileges are required to remove CoreDNS.")
    root, corefile, records, marker = _paths(stack)
    state = _snapshot(stack)
    if not state["configured"]:
        return
    if not _owned_unit(root):
        raise DNSError("Refusing to remove a systemd service WEAVE does not own.")
    _systemctl("disable", "--now", UNIT)
    UNIT_FILE.unlink()
    _systemctl("daemon-reload")
    marker.unlink()
    # Only remove the files created inside WEAVE's own DNS data directory.
    (root / "coredns").unlink(missing_ok=True)
    corefile.unlink(missing_ok=True)
    records.unlink(missing_ok=True)


def reconcile_linux(stack) -> None:
    state = _snapshot(stack)
    if not state["configured"]:
        return
    hostname, adapter = _identity(stack, state["interface"])
    if hostname != state["hostname"] or adapter["address"] != state["address"]:
        raise DNSError("Paired HTTPS hostname or LAN IP changed; reconfigure WEAVE DNS before student access.")
