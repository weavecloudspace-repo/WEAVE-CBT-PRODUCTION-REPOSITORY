"""First-install orchestration for the WEAVE CBT local server.

Registration is intentionally separate from the root Typer app:
    from weave_cli.commands.install import register
    register(app)

The deployment distribution must supply compose.yaml, nginx/nginx.conf, and
bootstrap scripts. The installation environment must be supplied separately;
.env.example is intentionally not a valid production configuration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import typer

from weave_cli.commands._shared import banner, error, info, success, warning
from weave_cli.docker.compose import DockerCompose, DockerComposeError
from weave_cli.docker.provider import LinuxDockerProvider, WindowsWslDockerProvider
from weave_cli.docker.runtime import DockerRuntime, DockerRuntimeError
from weave_cli.installation import (
    InstallationManager,
    InstallationState,
    InstallationStateError,
)
from weave_cli.platforms.base import BasePlatform, PlatformError
from weave_cli.platforms.linux import LinuxPlatform
from weave_cli.platforms.windows import WindowsPlatform

PROJECT_NAME = "weave-cbt"
WSL_DISTRIBUTION = "WeaveCBT"
MINIMUM_FREE_GIB = 10
STARTUP_TIMEOUT_SECONDS = 180
REQUIRED_ENV_KEYS = frozenset(
    {
        "WEAVE_IMAGE",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "REDIS_URL",
        "ENVIRONMENT",
        "WEAVE_API_BASE_URL",
    }
)
EXPECTED_RUNNING = {"postgres": 1, "redis": 1, "api": 3, "worker": 1, "nginx": 1}


class InstallError(RuntimeError):
    """Installation cannot proceed safely."""


class InstallationNeedsReboot(InstallError):
    """The operating system must restart before installation can resume."""


def _log(message: str) -> None:
    info(message)


def _detect_platform() -> tuple[BasePlatform, str, DockerRuntime]:
    if sys.platform == "win32":
        platform = WindowsPlatform(wsl_distribution=WSL_DISTRIBUTION)
        return platform, "wsl2", DockerRuntime(WindowsWslDockerProvider())
    if sys.platform.startswith("linux"):
        platform = LinuxPlatform()
        return platform, "native", DockerRuntime(LinuxDockerProvider())
    raise InstallError("WEAVE CBT installation supports Windows and Linux only.")


def _assets_root(assets_dir: Path | None) -> Path:
    if assets_dir is not None:
        return assets_dir.expanduser().resolve()

    # Source checkout convenience; packaged distributions must supply
    # --assets-dir until their deployment assets are bundled.
    checkout_deployment = Path(__file__).resolve().parents[4]
    if (checkout_deployment / "compose.yaml").is_file():
        return checkout_deployment
    raise InstallError(
        "Deployment assets are unavailable. Supply --assets-dir pointing to "
        "the directory containing compose.yaml, nginx/, and bootstrap/."
    )


def _read_environment(source: Path) -> dict[str, str]:
    try:
        content = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InstallError(f"Cannot read runtime environment file '{source}': {exc}") from exc

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if separator != "=" or not key.isidentifier():
            raise InstallError(f"Invalid environment assignment at line {line_number}.")
        if key in values:
            raise InstallError(f"Duplicate runtime environment setting '{key}'.")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value

    missing = sorted(key for key in REQUIRED_ENV_KEYS if not values.get(key))
    if missing:
        raise InstallError("Runtime environment is missing: " + ", ".join(missing))

    image = values["WEAVE_IMAGE"]
    if (
        image.endswith(":latest")
        or (":" not in image.rsplit("/", 1)[-1] and "@sha256:" not in image)
    ):
        raise InstallError("WEAVE_IMAGE must use an explicit version tag or digest.")

    password = values["POSTGRES_PASSWORD"]
    if len(password) < 16 or "change-this" in password.lower():
        raise InstallError(
            "POSTGRES_PASSWORD must be a real, randomly generated secret "
            "containing at least 16 characters, not the example password."
        )

    try:
        database = urlsplit(values["DATABASE_URL"])
        redis = urlsplit(values["REDIS_URL"])
        api_url = urlsplit(values["WEAVE_API_BASE_URL"])
        if database.scheme != "postgresql+asyncpg" or database.hostname != "postgres":
            raise ValueError("DATABASE_URL must use postgresql+asyncpg and host postgres")
        if (
            unquote(database.username or "") != values["POSTGRES_USER"]
            or unquote(database.password or "") != password
            or unquote(database.path.lstrip("/")) != values["POSTGRES_DB"]
        ):
            raise ValueError("DATABASE_URL credentials must match local PostgreSQL settings")
        if redis.scheme != "redis" or redis.hostname != "redis":
            raise ValueError("REDIS_URL must use redis://redis inside the Compose network")
        if api_url.scheme not in {"https", "http"} or not api_url.hostname:
            raise ValueError("WEAVE_API_BASE_URL must be an absolute HTTP(S) URL")
        if values["ENVIRONMENT"].lower() in {"prod", "production"} and api_url.scheme != "https":
            raise ValueError("Production WEAVE_API_BASE_URL must use HTTPS")
    except (ValueError, TypeError) as exc:
        raise InstallError(f"Invalid runtime environment: {exc}") from exc

    return values


def _existing_parent(directory: Path) -> Path:
    candidate = directory.resolve()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise InstallError(f"No existing parent directory for '{directory}'.")
        candidate = parent
    if not candidate.is_dir():
        raise InstallError(f"Installation parent '{candidate}' is not a directory.")
    return candidate


def _check_disk_space(directories: tuple[Path, Path], min_free_gib: int) -> None:
    checked: set[int] = set()
    threshold = min_free_gib * (1024**3)
    for directory in directories:
        parent = _existing_parent(directory)
        device = parent.stat().st_dev
        if device in checked:
            continue
        checked.add(device)
        free = shutil.disk_usage(parent).free
        if free < threshold:
            raise InstallError(
                f"Insufficient disk space on '{parent}': "
                f"{free / (1024**3):.1f} GiB free; {min_free_gib} GiB required."
            )


def _verify_assets(assets: Path) -> None:
    for relative in (
        "compose.yaml",
        "nginx/nginx.conf",
        "bootstrap/windows/bootstrap.ps1",
        "bootstrap/linux/bootstrap.sh",
    ):
        if not (assets / relative).is_file():
            raise InstallError(f"Missing deployment asset: '{assets / relative}'.")


def _check_staged_target(source: Path, target: Path) -> None:
    if target.exists():
        if not target.is_file():
            raise InstallError(f"Cannot install over non-file path '{target}'.")
        if source.read_bytes() != target.read_bytes():
            raise InstallError(
                f"'{target}' already exists with different content. "
                "Refusing to overwrite an existing or interrupted deployment."
            )


def _copy_staged_file(source: Path, target: Path, *, secret: bool = False) -> None:
    _check_staged_target(source, target)
    if target.is_file():
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            if secret and os.name != "nt":
                os.chmod(temporary, 0o600)
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())

        if secret and os.name == "nt":
            # Prevent ordinary users from reading database credentials.
            # Explicit local Administrators and SYSTEM can access runtime.env.
            result = subprocess.run(
                [
                    "icacls",
                    str(temporary),
                    "/inheritance:r",
                    "/grant:r",
                    "*S-1-5-18:F",
                    "*S-1-5-32-544:F",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                raise InstallError("Unable to restrict Windows runtime.env file permissions.")

        os.replace(temporary, target)
        temporary = None
    except OSError as exc:
        raise InstallError(f"Cannot stage installation file '{target}': {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _weave_wsl_distro_exists() -> bool:
    try:
        result = subprocess.run(
            ["wsl.exe", "--list", "--quiet"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    output = result.stdout
    try:
        listing = output.decode("utf-16") if b"\x00" in output else output.decode("utf-8-sig")
    except UnicodeError:
        return False
    return WSL_DISTRIBUTION.casefold() in (line.strip().casefold() for line in listing.splitlines())


def _ensure_docker(
    *,
    platform: BasePlatform,
    runtime: DockerRuntime,
    runtime_type: str,
    assets: Path,
    rootfs_archive: Path | None,
) -> None:
    if runtime.docker_engine_running():
        _log("Dedicated Docker Engine is already running.")
        return

    if runtime.docker_cli_available():
        _log("Starting existing Docker Engine.")
        try:
            platform.start_docker_engine()
        except PlatformError:
            # The bootstrap handles missing or unhealthy engines, and provides
            # platform-specific diagnostics if repair cannot succeed.
            pass
        if runtime.docker_engine_running():
            return

    if runtime_type == "wsl2" and rootfs_archive is None and not _weave_wsl_distro_exists():
        raise InstallError(
            "Dedicated WeaveCBT WSL distribution is missing. The current "
            "Windows bootstrap requires --rootfs-archive for a first install. "
            "Automatic Ubuntu rootfs acquisition is not implemented."
        )

    _log("Provisioning the Docker runtime using the platform bootstrap.")
    if runtime_type == "wsl2":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(assets / "bootstrap/windows/bootstrap.ps1"),
        ]
        if rootfs_archive is not None:
            command.extend(["-RootfsArchive", str(rootfs_archive)])
    else:
        command = ["bash", str(assets / "bootstrap/linux/bootstrap.sh")]

    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise InstallError(f"Unable to execute runtime bootstrap: {exc}") from exc

    if runtime_type == "wsl2" and result.returncode == 3010:
        raise InstallationNeedsReboot(
            "Windows reboot required. Restart Windows and rerun weave install "
            "with the same arguments. Installation data will be preserved."
        )

    if result.returncode != 0:
        raise InstallError(
            f"Runtime bootstrap failed (exit code {result.returncode}). "
            "Check bootstrap output; existing application data was not removed."
        )
    if not runtime.docker_engine_running():
        raise InstallError("Docker bootstrap completed, but Docker Engine is unreachable.")


def _compose_rows(runtime: DockerRuntime, compose: DockerCompose) -> list[dict]:
    command = [
        "compose",
        "-f",
        runtime.translate_path(compose.compose_file),
        "--env-file",
        runtime.translate_path(compose.env_file),
        "-p",
        compose.project_name,
        "ps",
        "--all",
        "--format",
        "json",
    ]
    result = runtime.run_docker_command(command, timeout=30)
    if not result.successful:
        raise InstallError("Unable to inspect Docker Compose service states.")

    raw = result.stdout.strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            return parsed
    except json.JSONDecodeError:
        pass

    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise InstallError("Docker Compose returned an unreadable JSON status.") from exc

    if not all(isinstance(row, dict) for row in rows):
        raise InstallError("Docker Compose service status has an unexpected format.")
    return rows


def _pending_services(rows: list[dict]) -> list[str]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("Service", "")), []).append(row)

    pending: list[str] = []
    for service, minimum in EXPECTED_RUNNING.items():
        entries = grouped.get(service, [])
        ready = sum(
            str(entry.get("State", "")).lower() == "running"
            and (
                service not in {"postgres", "redis"}
                or str(entry.get("Health", "")).lower() == "healthy"
            )
            for entry in entries
        )
        if ready < minimum:
            pending.append(f"{service} ({ready}/{minimum} ready)")

    migrations = grouped.get("bootstrap", [])
    completed = any(
        str(row.get("State", "")).lower() == "exited"
        and str(row.get("ExitCode", "1")) == "0"
        for row in migrations
    )
    if not completed:
        pending.append("bootstrap (waiting for successful initialization)")
    return pending


def _verify_started_stack(runtime: DockerRuntime, compose: DockerCompose) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_report = 0.0
    while True:
        outstanding = _pending_services(_compose_rows(runtime, compose))
        if not outstanding:
            return

        now = time.monotonic()
        if now >= deadline:
            raise InstallError(
                "Container readiness verification timed out: "
                + ", ".join(outstanding)
                + ". Containers and volumes were preserved for inspection."
            )
        if now - last_report >= 10:
            _log("Waiting for services: " + ", ".join(outstanding))
            last_report = now
        time.sleep(3)


def _perform_install(
    *,
    env_file: Path,
    assets_dir: Path | None,
    install_dir: Path | None,
    data_dir: Path | None,
    rootfs_archive: Path | None,
    version: str | None,
    min_free_gib: int,
) -> InstallationState:
    platform, runtime_type, runtime = _detect_platform()
    manager = InstallationManager(platform)
    install_directory = (install_dir or platform.default_install_directory).expanduser().resolve()
    data_directory = (data_dir or platform.default_data_directory).expanduser().resolve()
    assets = _assets_root(assets_dir)
    env_file = env_file.expanduser().resolve()

    _log("Running installation preflight.")
    if not platform.is_admin():
        raise InstallError("Administrator/root privileges are required.")
    if manager.exists():
        raise InstallError(
            f"WEAVE CBT is already registered at '{manager.state_path}'. "
            "Use the update or repair command; install will not overwrite it."
        )
    if install_directory == data_directory:
        raise InstallError("Program and data directories must be different.")
    if not env_file.is_file():
        raise InstallError(f"Runtime environment file '{env_file}' is missing.")
    if rootfs_archive is not None:
        rootfs_archive = rootfs_archive.expanduser().resolve()
        if not rootfs_archive.is_file():
            raise InstallError(f"Ubuntu rootfs archive '{rootfs_archive}' is missing.")

    _verify_assets(assets)
    values = _read_environment(env_file)
    _check_disk_space((install_directory, data_directory), min_free_gib)

    desired_files = (
        (assets / "compose.yaml", install_directory / "compose.yaml"),
        (assets / "nginx/nginx.conf", install_directory / "nginx/nginx.conf"),
        (env_file, data_directory / "runtime.env"),
    )
    for source, target in desired_files:
        _check_staged_target(source, target)

    # Bootstrap may alter OS features and require a restart, so preflight and
    # all file-collision checks must succeed before it runs.
    _ensure_docker(
        platform=platform,
        runtime=runtime,
        runtime_type=runtime_type,
        assets=assets,
        rootfs_archive=rootfs_archive,
    )
    _log("Configuring persistent runtime startup.")
    platform.ensure_runtime_persistence()

    # Record only an actual application deployment, not WSL/Docker bootstrap.
    _log("Staging application files and private runtime configuration.")
    for source, target in desired_files:
        _copy_staged_file(source, target, secret=(target.name == "runtime.env"))

    compose = DockerCompose(
        compose_file=install_directory / "compose.yaml",
        env_file=data_directory / "runtime.env",
        runtime=runtime,
        project_name=PROJECT_NAME,
    )
    _log("Validating Docker Compose configuration.")
    compose.config()

    _log("Downloading versioned application and infrastructure images.")
    compose.pull_weave_image()
    compose.pull_postgres_image()
    compose.pull_redis_image()
    compose.pull_nginx_image()

    _log("Starting PostgreSQL, Redis, API replicas, workers, and Nginx.")
    compose.start()
    _log("Verifying container states, PostgreSQL/Redis health and bootstrap completion.")
    _verify_started_stack(runtime, compose)

    state = InstallationState(
        install_directory=install_directory,
        data_directory=data_directory,
        installed_version=(version.strip() if version else values["WEAVE_IMAGE"]),
        runtime_type=runtime_type,
        installed_at=datetime.now(timezone.utc).isoformat(),
    )
    manager.create(state)
    return state


def install(
    env_file: Path = typer.Option(
        ..., "--env-file", help="Existing runtime.env configuration containing real secrets."
    ),
    assets_dir: Path | None = typer.Option(
        None, "--assets-dir", help="Directory containing the WEAVE deployment assets."
    ),
    install_dir: Path | None = typer.Option(
        None, "--install-dir", help="Override the platform's application directory."
    ),
    data_dir: Path | None = typer.Option(
        None, "--data-dir", help="Override the platform's mutable data directory."
    ),
    rootfs_archive: Path | None = typer.Option(
        None, "--rootfs-archive", help="Ubuntu rootfs tar required for fresh Windows WSL installs."
    ),
    version: str | None = typer.Option(
        None, "--version", help="Version recorded in install.json; defaults to the pinned image."
    ),
    min_free_gib: int = typer.Option(
        MINIMUM_FREE_GIB, "--min-free-gib", min=1, help="Minimum free GiB on each target disk."
    ),
) -> None:
    """Install WEAVE CBT without overwriting existing application data."""
    banner("Installing local server")
    try:
        state = _perform_install(
            env_file=env_file,
            assets_dir=assets_dir,
            install_dir=install_dir,
            data_dir=data_dir,
            rootfs_archive=rootfs_archive,
            version=version,
            min_free_gib=min_free_gib,
        )
    except InstallationNeedsReboot as exc:
        warning(str(exc))
        raise typer.Exit(code=10) from exc
    except (InstallError, InstallationStateError, DockerRuntimeError, DockerComposeError, PlatformError, OSError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc

    typer.echo()
    success("Installation verified and registered.")
    info(f"Version: {state.installed_version}")
    info(f"Install directory: {state.install_directory}")
    info(f"Data directory: {state.data_directory}")
    info(f"State file: {InstallationManager(_detect_platform()[0]).state_path}")


def register(app: typer.Typer) -> None:
    """Register weave install with the single root CLI app."""
    app.command(name="install")(install)
