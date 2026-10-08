
import sys

import typer

from weave_cli.docker.compose import DockerCompose, DockerComposeError
from weave_cli.docker.provider import LinuxDockerProvider, WindowsWslDockerProvider
from weave_cli.docker.runtime import DockerRuntime, DockerRuntimeError
from weave_cli.installation import InstallationManager, InstallationStateError
from weave_cli.platforms.linux import LinuxPlatform
from weave_cli.platforms.windows import WindowsPlatform


def status() -> None:
    """Display WEAVE CBT installation and container status."""

    if sys.platform == "win32":
        platform = WindowsPlatform(wsl_distribution="WeaveCBT")
        provider = WindowsWslDockerProvider()
    elif sys.platform.startswith("linux"):
        platform = LinuxPlatform()
        provider = LinuxDockerProvider()
    else:
        typer.echo("[WEAVE][ERROR] Unsupported operating system.", err=True)
        raise typer.Exit(code=1)

    manager = InstallationManager(platform)

    if not manager.exists():
        typer.echo("[WEAVE] Status: Not installed")
        raise typer.Exit(code=1)

    try:
        installation = manager.load()

        typer.echo(f"[WEAVE] Installed version: {installation.installed_version}")
        typer.echo(f"[WEAVE] Runtime: {installation.runtime_type}")

        runtime = DockerRuntime(provider)

        if not runtime.docker_engine_running():
            typer.echo("[WEAVE] Docker Engine: Not running")
            raise typer.Exit(code=1)

        typer.echo("[WEAVE] Docker Engine: Running")

        compose = DockerCompose(
            compose_file=installation.install_directory / "compose.yaml",
            env_file=installation.data_directory / "runtime.env",
            runtime=runtime,
        )

        result = compose.status()

        typer.echo("\n[WEAVE] Container status:")
        typer.echo(result.stdout or "No running containers found.")

    except (InstallationStateError, DockerComposeError, DockerRuntimeError) as exc:
        typer.echo(f"[WEAVE][ERROR] {exc}", err=True)
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    """Register the status command with the root CLI."""
    app.command(name="status")(status)
