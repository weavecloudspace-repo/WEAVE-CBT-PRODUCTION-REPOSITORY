"""Portable, offline WEAVE CBT client hostname mapping (Windows and Linux).

The installed standalone weave executable doubles as the client tool when renamed
WEAVE-CBT-Client-Setup.exe / weave-cbt-client-setup. No client Python, WSL,
Docker or live cloud connection is required. It uses an adjacent JSON file.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import typer

CLIENT_WINDOWS = "WEAVE-CBT-Client-Setup.exe"
CLIENT_LINUX = "weave-cbt-client-setup"
CONFIG_NAME = "weave-client.json"
BEGIN = "# BEGIN WEAVE CBT CLIENT RESOLUTION"
END = "# END WEAVE CBT CLIENT RESOLUTION"
DOMAIN = re.compile(r"[a-z0-9-]+\.[a-z0-9-]+\.cbt(?:-staging)?\.weavecloudspace\.com\Z")
PRIVATE_RANGES = tuple(ipaddress.ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
client_app = typer.Typer(help="Export an offline Windows or Linux student-PC setup package.")


class ClientResolutionError(RuntimeError):
    """Refuse unsafe or ambiguous changes to the client hosts file."""


def validated(data: object) -> dict[str, object]:
    if not isinstance(data, dict) or set(data) != {"schema", "hostname", "address"} or data["schema"] != 1:
        raise ClientResolutionError("Unsupported client configuration format.")
    hostname, address = data["hostname"], data["address"]
    if not isinstance(hostname, str) or not DOMAIN.fullmatch(hostname):
        raise ClientResolutionError("Invalid or unpaired WEAVE CBT hostname.")
    if not isinstance(address, str):
        raise ClientResolutionError("Invalid school LAN address.")
    try:
        ip = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError as exc:
        raise ClientResolutionError("Invalid IPv4 address.") from exc
    if not any(ip in network for network in PRIVATE_RANGES) or str(ip) != address:
        raise ClientResolutionError("School LAN address must be a canonical private IPv4 address.")
    return {"schema": 1, "hostname": hostname, "address": address}


def _load_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ClientResolutionError(f"Missing or unsafe configuration: {path}")
    try:
        return validated(json.loads(path.read_text(encoding="utf-8")))
    except (UnicodeError, ValueError) as exc:
        raise ClientResolutionError(f"Unreadable WEAVE configuration: {path}") from exc


def _binary(platform: str, installation: Path) -> Path:
    """Only copy a real, locally installed standalone manager binary."""
    suffix = "weave.exe" if platform == "windows" else "weave"
    candidates = [installation / suffix, Path(sys.executable)]
    which = shutil.which(suffix)
    if which:
        candidates.append(Path(which))
    expected = b"MZ" if platform == "windows" else b"\x7fELF"
    for candidate in candidates:
        if candidate.name.lower() not in {suffix.lower(), CLIENT_WINDOWS.lower(), CLIENT_LINUX}:
            continue
        try:
            with candidate.open("rb") as binary:
                if binary.read(len(expected)) == expected:
                    return candidate
        except OSError:
            pass
    raise ClientResolutionError("The installed standalone WEAVE CLI binary is missing or invalid.")


def export_package(output_dir: Path, *, installation: Path, hostname: str,
                   address: str, platform: str) -> Path:
    """Build a portable ZIP, without shipping secret server identity or config."""
    if platform not in {"windows", "linux"}:
        raise ClientResolutionError("Client export supports Windows and Linux only.")
    configuration = validated({"schema": 1, "hostname": hostname, "address": address})
    binary = _binary(platform, installation)
    target_name = CLIENT_WINDOWS if platform == "windows" else CLIENT_LINUX
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise ClientResolutionError("Refusing to export through a symlinked output directory.")
    archive = output_dir / ("WEAVE-CBT-Client-Windows.zip" if platform == "windows"
                            else "WEAVE-CBT-Client-Linux.zip")
    descriptor, temporary = tempfile.mkstemp(prefix=".weave-client-", suffix=".zip", dir=output_dir)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
                entry = zipfile.ZipInfo(target_name)
                entry.create_system = 3
                entry.external_attr = (0o755 << 16)
                with binary.open("rb") as source, zipped.open(entry, "w", force_zip64=True) as dest:
                    shutil.copyfileobj(source, dest, 1024 * 1024)
                zipped.writestr(CONFIG_NAME, json.dumps(configuration, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, archive)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return archive


def _source_configuration(stack) -> dict[str, object]:
    from weave_cli.commands import network
    from weave_cli.commands.lan import LanError, _read_state
    hostname = network._https_hostname(stack)
    if not hostname:
        raise ClientResolutionError("Activate the paired HTTPS hostname using 'weave tls' first.")
    if stack.installation.runtime_type == "wsl2":
        mapping = _read_state(stack.installation.data_directory)
        if not mapping:
            raise ClientResolutionError("Run 'weave network setup' before exporting clients.")
        address = mapping["listen_address"]
    else:
        choice = network.recommend(network.inventory())
        if not choice:
            raise ClientResolutionError("Cannot identify one trusted LAN adapter for the Linux server.")
        address = choice["address"]
    return validated({"schema": 1, "hostname": hostname, "address": address})


@client_app.command("export")
def cli_export(
    output: Path = typer.Option(Path.cwd(), "--output", help="Directory for the USB-ready ZIP."),
) -> None:
    """Export an offline setup for client computers of the current OS."""
    from weave_cli.commands._shared import banner, error, get_stack, info, success
    try:
        stack = get_stack()
        platform = "windows" if sys.platform == "win32" else "linux" if sys.platform.startswith("linux") else ""
        configuration = _source_configuration(stack)
        archive = export_package(
            output, installation=stack.installation.install_directory,
            hostname=str(configuration["hostname"]), address=str(configuration["address"]),
            platform=platform,
        )
        banner("Offline client setup")
        success(f"Created {archive}")
        info(f"Mapping: {configuration['address']}  {configuration['hostname']}")
        info("Extract the ZIP on each PC and run the setup executable as administrator/root.")
        info("The utility replaces only verified WEAVE-managed hosts entries and flushes DNS.")
    except (ClientResolutionError, OSError, RuntimeError) as exc:
        error(str(exc))
        raise typer.Exit(1) from exc


def _block(text: str, config: dict[str, object], previous: dict[str, object] | None) -> str:
    """Return replacement hosts content, rejecting ambiguous/malformed ownership."""
    lines = text.splitlines(keepends=True)
    beginnings = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    endings = [i for i, line in enumerate(lines) if line.strip() == END]
    if len(beginnings) != len(endings) or len(beginnings) > 1:
        raise ClientResolutionError("Malformed or duplicate WEAVE hosts markers; no changes made.")
    start = beginnings[0] if beginnings else None
    end = endings[0] if endings else None
    if start is not None:
        if end is None or end <= start or end != start + 2:
            raise ClientResolutionError("WEAVE-owned hosts block is modified; refusing replacement.")
        mapping = lines[start + 1].strip().split()
        if len(mapping) != 2:
            raise ClientResolutionError("Existing WEAVE hosts mapping is malformed.")
        old = validated({"schema": 1, "address": mapping[0], "hostname": mapping[1]})
        if previous is not None and previous != old:
            raise ClientResolutionError("Saved WEAVE state conflicts with hosts file; inspect before replacing.")
        kept = lines[:start] + lines[end + 1:]
    else:
        if previous is not None:
            raise ClientResolutionError("Saved WEAVE state exists but its hosts block is missing.")
        kept = lines
    # Refuse any hostname collision outside the owned region; never take over
    # entries placed by the operating system, users or other administrators.
    protected = {str(config["hostname"])}
    if previous:
        protected.add(str(previous["hostname"]))
    for line in kept:
        tokens = line.split("#", 1)[0].split()
        if tokens and any(token.casefold() in protected for token in tokens[1:]):
            raise ClientResolutionError("Unmanaged hosts entry conflicts with a WEAVE hostname.")
    newline = "\r\n" if "\r\n" in text else "\n"
    remainder = "".join(kept)
    if remainder and not remainder.endswith(("\r", "\n")):
        remainder += newline
    return remainder + newline.join((
        BEGIN, str(config["address"]) + " " + str(config["hostname"]), END, "",
    ))


def _storage() -> tuple[Path, Path]:
    if os.name == "nt":
        root = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "WeaveCBT" / "ClientNetwork"
        hosts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    else:
        root, hosts = Path("/var/lib/weave-cbt/client-network"), Path("/etc/hosts")
    return root, hosts


def _read_hosts(path: Path) -> tuple[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ClientResolutionError("Missing or symlinked system hosts file.")
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ClientResolutionError("Unexpected hosts file encoding; no modifications made.")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        if os.name == "nt":
            return raw.decode("cp1252"), "cp1252"
        raise ClientResolutionError("Non-UTF-8 Linux hosts file; inspect encoding before changes.")


def _atomic(path: Path, content: bytes, *, reference: Path | None = None) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".weave-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if reference and reference.exists():
            shutil.copystat(reference, tmp)
            if os.name != "nt":
                stat = reference.stat()
                os.chown(tmp, stat.st_uid, stat.st_gid)
        elif os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply(config: dict[str, object], *, hosts: Path, state_dir: Path,
          remove: bool = False) -> bool:
    """Update/restore WEAVE-owned block and durable state; keep a disk backup."""
    state_dir.mkdir(parents=True, exist_ok=True)
    if state_dir.is_symlink():
        raise ClientResolutionError("Unsafe WEAVE client state directory.")
    if os.name != "nt":
        os.chmod(state_dir, 0o700)
    state_path = state_dir / "config.json"
    previous = _load_json(state_path) if state_path.exists() else None
    text, encoding = _read_hosts(hosts)
    if remove:
        if previous is None and BEGIN not in text and END not in text:
            return False
        # Reuse strict ownership validation before removing anything.
        _block(text, config, previous)
        lines = text.splitlines(keepends=True)
        starts = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
        ends = [i for i, line in enumerate(lines) if line.strip() == END]
        revised = "".join(lines[:starts[0]] + lines[ends[0] + 1:]) if starts else text
    else:
        revised = _block(text, config, previous)
    if revised == text and (not remove and previous == config):
        return False
    backup = state_dir / "hosts.previous.bak"
    if backup.is_symlink():
        raise ClientResolutionError("Unsafe backup path.")
    _atomic(backup, hosts.read_bytes())
    try:
        _atomic(hosts, revised.encode(encoding), reference=hosts)
        if remove:
            state_path.unlink(missing_ok=True)
        else:
            _atomic(state_path, (json.dumps(config, sort_keys=True) + "\n").encode("utf-8"),
                    reference=state_path if state_path.exists() else None)
    except (OSError, ValueError):
        _atomic(hosts, backup.read_bytes(), reference=hosts)
        raise
    return True


def _flush_dns() -> None:
    if os.name == "nt":
        candidates = [["ipconfig", "/flushdns"]]
    else:
        candidates = []
        if shutil.which("resolvectl"):
            candidates.append(["resolvectl", "flush-caches"])
        if shutil.which("systemd-resolve"):
            candidates.append(["systemd-resolve", "--flush-caches"])
        if shutil.which("nscd"):
            candidates.append(["nscd", "-i", "hosts"])
    if not candidates:
        print("[WEAVE][INFO] No system DNS cache-flush service found; hosts lookup is immediate.")
        return
    errors = []
    for cmd in candidates:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=20, check=False)
            if result.returncode == 0:
                print("[WEAVE][OK] DNS cache flushed automatically.")
                return
            errors.append(f"{cmd[0]} exit {result.returncode}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{cmd[0]}: {exc}")
    raise ClientResolutionError("DNS cache flush failed: " + "; ".join(errors))


def _verify(config: dict[str, object], *, remove: bool = False) -> None:
    hostname = str(config["hostname"])
    address = str(config["address"])
    try:
        ips = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
        if remove:
            print("[WEAVE][INFO] WEAVE hosts mapping removed; no resolution assertion after removal.")
            return
        if address not in ips:
            print(f"[WEAVE][WARN] Hostname resolves to {sorted(ips)}, not expected {address}.")
            return
        print(f"[WEAVE][OK] Hostname resolves to {address}.")
    except OSError as exc:
        print(f"[WEAVE][WARN] Hostname lookup failed: {exc}")
        return
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(f"https://{hostname}/student", timeout=5) as response:
            response.read(1)
        print("[WEAVE][OK] CBT server HTTPS connection and certificate verified.")
    except (OSError, urllib.error.URLError, ValueError) as exc:
        print(f"[WEAVE][WARN] Mapping applied, but HTTPS is not verified: {exc}")


def _elevated() -> bool:
    if os.name == "nt":
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _request_elevation() -> int:
    if os.name == "nt":
        import ctypes
        argument = "--remove" if "--remove" in sys.argv[1:] else ""
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, argument,
                                                       str(Path(sys.executable).parent), 1)
        if result <= 32:
            raise ClientResolutionError("Windows administrator elevation was denied.")
        return 0
    runner = ["sudo"] if sys.stdin.isatty() and shutil.which("sudo") else ["pkexec"]
    if not shutil.which(runner[0]):
        raise ClientResolutionError("Administrator/root permissions are required (sudo or pkexec).")
    return subprocess.call([*runner, sys.executable, *sys.argv[1:]])


def main_client() -> None:
    """Entrypoint for the renamed compiled executable, no WEAVE server needed."""
    try:
        args = sys.argv[1:]
        if any(a not in {"--remove"} for a in args) or len(args) > 1:
            raise ClientResolutionError("Usage: client setup executable [--remove]")
        executable_dir = Path(sys.executable).resolve().parent
        config = _load_json(executable_dir / CONFIG_NAME)
        print("WEAVE CBT client network setup")
        print(f"School server: {config['address']} -> {config['hostname']}")
        print("Only WEAVE-managed entries in the local hosts file will be changed.")
        if not _elevated():
            sys.exit(_request_elevation())
        state_dir, hosts = _storage()
        changed = apply(config, hosts=hosts, state_dir=state_dir, remove="--remove" in args)
        print("[WEAVE][OK] Network mapping removed." if "--remove" in args
              else "[WEAVE][OK] Network mapping configured.")
        if changed:
            _flush_dns()
        if "--remove" not in args:
            _verify(config)
    except (ClientResolutionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[WEAVE][ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if os.name == "nt" and sys.stdin.isatty():
            try:
                input("Press Enter to close...")
            except EOFError:
                pass


def register(network_app: typer.Typer) -> None:
    network_app.add_typer(client_app, name="client")
