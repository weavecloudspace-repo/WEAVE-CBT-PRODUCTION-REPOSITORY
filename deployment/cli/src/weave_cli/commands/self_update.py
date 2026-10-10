"""Update CLI and Desktop Manager independently of the CBT database/image.

Official channel-matched GitHub Release, checksum verified before installation.
No Docker service is stopped by manager update.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import typer

from weave_cli.commands._shared import banner, error, info, success, warning
from weave_cli.commands.install import _assets_root, _read_release_manifest

_REPO = "weavecloudspace-repo/WEAVE-CBT-PRODUCTION-REPOSITORY"
_RELEASES = f"https://api.github.com/repos/{_REPO}/releases?per_page=50"
_VERSION = re.compile(r"^(?:staging-|v)([0-9]+)\.([0-9]+)\.([0-9]+)$")
_HASH = re.compile(r"^[a-f0-9]{64}$")


class ManagerUpdateError(RuntimeError):
    pass


def _get(url: str, *, cap: int) -> bytes:
    req = Request(url, headers={"User-Agent": "WEAVE-CBT-Manager/1", "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=45) as response:
        data = response.read(cap + 1)
    if len(data) > cap:
        raise ManagerUpdateError("Update metadata exceeds safe size limit.")
    return data


def _version(tag: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(tag)
    if match is None:
        raise ManagerUpdateError("Unrecognized manager release version.")
    return tuple(int(p) for p in match.groups())


def _latest(channel: str) -> dict:
    data = json.loads(_get(_RELEASES, cap=2_000_000))
    if not isinstance(data, list):
        raise ManagerUpdateError("Invalid GitHub release response.")
    prefix = "staging-" if channel == "staging" else "v"
    matches = [
        release for release in data
        if isinstance(release, dict) and not release.get("draft")
        and bool(release.get("prerelease")) == (channel == "staging")
        and isinstance(release.get("tag_name"), str)
        and release["tag_name"].startswith(prefix)
        and _VERSION.fullmatch(release["tag_name"])
    ]
    if not matches:
        raise ManagerUpdateError(f"No published {channel} manager release found.")
    return max(matches, key=lambda r: _version(r["tag_name"]))


def _official_asset(release: dict, filename: str) -> str:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ManagerUpdateError("Release has no assets.")
    matching = [item.get("browser_download_url") for item in assets
                if isinstance(item, dict) and item.get("name") == filename]
    if len(matching) != 1 or not isinstance(matching[0], str):
        raise ManagerUpdateError(f"Official release asset missing: {filename}")
    url = matching[0]
    expected = f"https://github.com/{_REPO}/releases/download/{release['tag_name']}/{filename}"
    if url != expected:
        raise ManagerUpdateError("Update artifact URL does not match the official release.")
    return url


def _expected_hash(release: dict, filename: str) -> str:
    checksums = _get(_official_asset(release, "SHA256SUMS"), cap=64_000)
    matches = []
    for line in checksums.decode("utf-8").splitlines():
        entry = line.split(maxsplit=1)
        if len(entry) == 2 and entry[1].lstrip("*") == filename and _HASH.fullmatch(entry[0]):
            matches.append(entry[0])
    if len(matches) != 1:
        raise ManagerUpdateError("Selected installer has no unique SHA-256 checksum.")
    return matches[0]


def _download_verified(release: dict, filename: str, checksum: str) -> Path:
    folder = Path(tempfile.mkdtemp(prefix="weave-manager-update-"))
    target = folder / filename
    digest = hashlib.sha256()
    total = 0
    req = Request(_official_asset(release, filename), headers={"User-Agent": "WEAVE-CBT-Manager/1"})
    try:
        with urlopen(req, timeout=60) as source, target.open("xb") as output:
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > 500 * 1024 * 1024:
                    raise ManagerUpdateError("Installer exceeds allowed download size.")
                digest.update(chunk)
                output.write(chunk)
        if total == 0 or digest.hexdigest() != checksum:
            raise ManagerUpdateError("SHA-256 verification failed; update was not launched.")
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def self_update(
    check: bool = typer.Option(False, "--check", help="Check only; do not download or install."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm starting the official package installer."),
) -> None:
    """Check or install the latest channel-matched manager and CLI release."""
    banner("Desktop and CLI manager update")
    try:
        manifest = _read_release_manifest(_assets_root(None))
        if manifest is None:
            raise ManagerUpdateError("A packaged manager release is required.")
        channel = manifest["channel"]
        current = _version(manifest["version"])
        release = _latest(channel)
        newest = _version(release["tag_name"])
        info(f"Installed manager: {manifest['version']} ({channel})")
        info(f"Latest official manager: {release['tag_name']}")
        if newest <= current:
            success("The desktop and CLI manager are already up to date.")
            return
        if check:
            warning("A newer manager release is available. Run 'weave self-update' to install it.")
            return
        if not yes and not typer.confirm(
            "Update the manager and CLI? The CBT server will remain running.", default=False
        ):
            warning("Manager update cancelled.")
            return
        if sys.platform == "win32":
            filename = ("WEAVE-CBT-Staging-Desktop-Setup.exe" if channel == "staging"
                        else "WEAVE-CBT-Desktop-Setup.exe")
        elif sys.platform.startswith("linux"):
            filename = f"weave-cbt-desktop-{channel}-linux-amd64.deb"
        else:
            raise ManagerUpdateError("Only Windows and Ubuntu/Debian are supported.")
        expected = _expected_hash(release, filename)
        info(f"Downloading and verifying {filename}...")
        installer = _download_verified(release, filename, expected)
        success("Official release checksum verified.")
        if sys.platform == "win32":
            # The signed-in user approves UAC. The external Inno Setup process
            # replaces the binaries after this CLI/GUI process terminates.
            os.startfile(str(installer), "runas")
            success("Installer launched. Complete the setup wizard; close the Desktop Manager.")
        else:
            if os.geteuid() != 0:
                raise ManagerUpdateError("Run as root (sudo) to install the verified .deb package.")
            completed = subprocess.run(["apt-get", "install", "-y", str(installer)], check=False)
            if completed.returncode != 0:
                raise ManagerUpdateError(f"APT upgrade failed (exit {completed.returncode}).")
            success("Desktop and CLI manager upgraded. Reopen the Desktop Manager.")
    except (ManagerUpdateError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="self-update")(self_update)
