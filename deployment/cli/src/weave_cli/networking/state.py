"""Persist one approved school interface independently of NAT forwarding state.

No migration grants permission to change a Windows network profile: the school
administrator must explicitly opt in using 'weave network prefer set'.
"""
from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from pathlib import Path

SCHEMA = 2
FILE = "network-policy.json"


class NetworkPolicyError(RuntimeError):
    pass


def path(data: Path) -> Path:
    return data / FILE


def _validate(value: dict) -> dict:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise NetworkPolicyError("Unsupported WEAVE network policy schema.")
    if value.get("transport") not in {"nat", "mirrored", "native"}:
        raise NetworkPolicyError("Unrecognized saved WEAVE transport.")
    if type(value.get("remote_enabled")) is not bool:
        raise NetworkPolicyError("Invalid remote-access preference.")
    if type(value.get("restore_private")) is not bool:
        raise NetworkPolicyError("Invalid profile recovery approval.")
    address, subnet = value.get("address"), value.get("subnet")
    if address is not None or subnet is not None:
        try:
            ip = ipaddress.ip_address(address)
            network = ipaddress.ip_network(subnet, strict=True)
            if ip.version != 4 or ip not in network or not ip.is_private:
                raise ValueError("Not a school IPv4 interface.")
        except (ValueError, TypeError) as exc:
            raise NetworkPolicyError("Invalid saved school interface or subnet.") from exc
    if not isinstance(value.get("interface_name"), (str, type(None))):
        raise NetworkPolicyError("Invalid saved interface name.")
    if not isinstance(value.get("interface_guid"), (str, type(None))):
        raise NetworkPolicyError("Invalid saved interface identity.")
    return value


def load(data: Path) -> dict | None:
    target = path(data)
    if not target.exists():
        return None
    if target.is_symlink() or not target.is_file():
        raise NetworkPolicyError("Unsafe network policy path.")
    try:
        return _validate(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise NetworkPolicyError("Cannot read saved WEAVE network policy.") from exc


def save(data: Path, value: dict) -> None:
    _validate(value)
    target = path(data)
    if target.is_symlink():
        raise NetworkPolicyError("Refusing to write a linked network policy.")
    data.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=data, prefix=".network-policy-",
            delete=False,
        ) as handle:
            name = Path(handle.name)
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o600)
        os.replace(name, target)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def legacy_policy(data: Path, *, runtime_type: str) -> dict:
    """Import existing NAT settings WITHOUT guessing an adapter or new trust."""
    address = subnet = None
    transport = "native" if runtime_type != "wsl2" else "nat"
    old = data / "lan.json"
    if old.exists():
        if old.is_symlink() or not old.is_file():
            raise NetworkPolicyError("Unsafe legacy LAN ownership record.")
        try:
            record = json.loads(old.read_text(encoding="utf-8"))
            address, subnet = record["listen_address"], record["client_subnet"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise NetworkPolicyError("Unreadable legacy LAN record; refusing migration.") from exc
    return _validate({
        "schema": SCHEMA, "transport": transport,
        "address": address, "subnet": subnet,
        "interface_name": None, "interface_guid": None,
        "restore_private": False, "remote_enabled": False,
    })


def load_or_import(data: Path, *, runtime_type: str) -> dict:
    existing = load(data)
    if existing is not None:
        return existing
    value = legacy_policy(data, runtime_type=runtime_type)
    save(data, value)
    return value
