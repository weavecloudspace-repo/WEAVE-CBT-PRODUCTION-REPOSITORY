"""Inspect the packaged manager channel and deployment assets without admin access."""

from __future__ import annotations

import typer

from weave_cli.commands._shared import banner, error, info, success
from weave_cli.commands.install import (
    InstallError,
    _assets_root,
    _read_release_manifest,
    _verify_assets,
)


def release() -> None:
    """Show the bundled release channel, API URL, and pinned Docker image."""
    banner("Manager release")
    try:
        assets = _assets_root(None)
        _verify_assets(assets)
        manifest = _read_release_manifest(assets)
        if manifest is None:
            raise InstallError(
                "This source checkout has no bundled release manifest; "
                "release details are only available in official installers."
            )
    except (InstallError, OSError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc

    success("Release metadata and all deployment assets verified.")
    info(f"Channel: {manifest['channel']}")
    info(f"Manager version: {manifest['version']}")
    info(f"WEAVE API: {manifest['api']}")
    info(f"CBT image: {manifest['image']}")
    info(f"Ubuntu WSL SHA-256: {manifest['ubuntu_sha']}")


def register(app: typer.Typer) -> None:
    app.command(name="release")(release)
