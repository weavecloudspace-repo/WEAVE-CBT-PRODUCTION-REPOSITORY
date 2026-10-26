"""Repeatable, explicit fresh CBT installation for disposable test machines.

Never silently remove production exam records. The CLI/GUI are not uninstalled:
only this Compose project's data and deployment configuration are reset.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import typer

from weave_cli.commands._shared import banner, error, info, success, warning
from weave_cli.commands.install import (
    _detect_platform, _perform_install, InstallError,
    MINIMUM_FREE_GIB, PROJECT_NAME,
)
from weave_cli.commands.lan import LanError
from weave_cli.commands.purge_cleanup import preflight, cleanup_host, verify_host, clear_dns_artifacts
from weave_cli.commands.network_dns import DNSError
from weave_cli.commands.purge_safety import PurgeSafetyError, verify_purged_resources
from weave_cli.commands.update_recovery import guard_pending_update
from weave_cli.docker.compose import DockerCompose, DockerComposeError
from weave_cli.docker.runtime import DockerRuntimeError
from weave_cli.installation import InstallationManager, InstallationStateError
from weave_cli.platforms.base import PlatformError


def _project_resources(runtime) -> tuple[str, str]:
    """Only query Compose-labelled resources belonging to WEAVE's project."""
    filters = ["--filter", f"label=com.docker.compose.project={PROJECT_NAME}"]
    containers = runtime.run_docker_command(
        ["ps", "-aq", *filters], timeout=30
    )
    volumes = runtime.run_docker_command(
        ["volume", "ls", "-q", *filters], timeout=30
    )
    if not containers.successful or not volumes.successful:
        raise InstallError("Cannot verify Docker resources; refusing an unsafe reset.")
    return containers.stdout.strip(), volumes.stdout.strip()


def _archive_stale_files(install_dir: Path, data_dir: Path) -> Path | None:
    """Move only known WEAVE-owned configuration to a private backup folder."""
    targets = (
        (data_dir / "runtime.env", "runtime.env"),
        (data_dir / "network-policy.json", "network-policy.json"),
        (data_dir / "deployment-assets.json", "deployment-assets.json"),
        (data_dir / "tls.enabled", "tls.enabled"),
        (data_dir / "lan.json", "lan.json"),
        (data_dir / "tls-lan.json", "tls-lan.json"),
        (data_dir / "update-recovery.json", "update-recovery.json"),
        (data_dir / ".cbt-update.lock", ".cbt-update.lock"),
        (install_dir / "compose.yaml", "compose.yaml"),
        (install_dir / "nginx" / "nginx.conf", "nginx.conf"),
        (install_dir / "nginx" / "reload-watch.sh", "reload-watch.sh"),
        (install_dir / "certificates" / "hooks.py", "hooks.py"),
    )
    existing = [(path, name) for path, name in targets if path.exists()]
    if not existing:
        return None
    for path, _ in existing:
        if not path.is_file() or path.is_symlink():
            raise InstallError(f"Unexpected installation path: {path}")
    data_dir.mkdir(parents=True, exist_ok=True)
    archive = Path(tempfile.mkdtemp(prefix="reinstall-backup-", dir=data_dir))
    if os.name != "nt":
        archive.chmod(0o700)
    for source, name in existing:
        os.replace(source, archive / name)
    return archive


def reinstall(
    purge_data: bool = typer.Option(
        False, "--purge-data",
        help="Permanently delete WEAVE CBT Compose volumes and rebuild with new credentials.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip initial confirmation, not DELETE DATA verification.",
    ),
) -> None:
    """Freshly install the release-pinned server; explicitly purge test data if requested."""
    banner("Fresh CBT installation")
    try:
        platform, runtime_type, runtime = _detect_platform()
        if not platform.is_admin():
            raise InstallError("Run an elevated Administrator/root terminal.")
        manager = InstallationManager(platform)
        data_dir = platform.default_data_directory
        install_dir = platform.default_install_directory
        if manager.exists():
            state = manager.load()
            if state.install_directory != install_dir or state.data_directory != data_dir:
                raise InstallError("Installation uses custom paths. Back it up and uninstall explicitly.")
        if not purge_data:
            guard_pending_update(data_dir)
        leftovers = any(p.exists() for p in (
            data_dir / "runtime.env",
            install_dir / "compose.yaml",
            data_dir / "tls.enabled",
        ))
        if (manager.exists() or leftovers) and not purge_data:
            raise InstallError(
                "Existing deployment state detected. Use 'weave reinstall --purge-data' "
                "only on a disposable test server; exam records would be erased."
            )
        if purge_data:
            warning("DESTRUCTIVE: ALL WEAVE CBT PostgreSQL, exam data, and machine identity volumes will be deleted.")
            if not yes and not typer.confirm("Purge WEAVE CBT data and reinstall?", default=False):
                warning("Fresh installation cancelled.")
                return
            if typer.prompt("Type DELETE DATA to confirm") != "DELETE DATA":
                warning("Fresh installation cancelled; no data deleted.")
                return
        if not runtime.docker_engine_running():
            platform.start_docker_engine()
        if not runtime.docker_engine_running():
            raise InstallError("Docker Engine is not available.")
        containers, volumes = _project_resources(runtime)
        if purge_data:
            # Reuse exactly the host cleanup contract of 'uninstall --purge-volumes'.
            host = SimpleNamespace(
                installation=SimpleNamespace(
                    runtime_type=runtime_type, data_directory=data_dir,
                    install_directory=install_dir,
                ),
                runtime=runtime, platform=platform,
            )
            snapshot = preflight(host)
            cleanup_host(host)
            if containers or volumes:
                if not (install_dir / "compose.yaml").is_file() or not (data_dir / "runtime.env").is_file():
                    raise InstallError(
                        "Existing WEAVE Docker data cannot be safely attributed to a Compose file. "
                        "Use the normal uninstall/recovery workflow."
                    )
                stack = DockerCompose(
                    compose_file=install_dir / "compose.yaml",
                    env_file=data_dir / "runtime.env",
                    runtime=runtime, project_name=PROJECT_NAME,
                )
                info("Removing only WEAVE CBT project containers and named data volumes...")
                stack.destroy()
            # Also detect stale or unlabeled TLS volumes with known WEAVE
            # names. Refuse to reuse old certificates during first start.
            verify_purged_resources(runtime)
            verify_host(host, snapshot)
            # An earlier normal uninstall could leave CoreDNS files after
            # its ownership marker and service were removed.
            clear_dns_artifacts(data_dir, install_dir)
            platform.remove_runtime_persistence()
            if manager.exists():
                manager.delete()
            archive = _archive_stale_files(install_dir, data_dir)
            if archive:
                warning(f"Old configuration archived securely at {archive}; previous data volumes are gone.")
        elif containers or volumes:
            raise InstallError("WEAVE Docker data exists; cannot claim a fresh install without an explicit purge.")

        info("Installing the current manager's version-pinned CBT image...")
        state = _perform_install(
            env_file=None, assets_dir=None, install_dir=None, data_dir=None,
            rootfs_archive=None, version=None, min_free_gib=MINIMUM_FREE_GIB,
        )
        success("Fresh WEAVE CBT installation verified.")
        info(f"Image: {state.installed_version}")
        info("Open http://localhost/ to pair this fresh server with WEAVE Cloud.")
    except (InstallError, InstallationStateError, DockerRuntimeError,
            DockerComposeError, PlatformError, LanError, DNSError, PurgeSafetyError, OSError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="reinstall")(reinstall)
