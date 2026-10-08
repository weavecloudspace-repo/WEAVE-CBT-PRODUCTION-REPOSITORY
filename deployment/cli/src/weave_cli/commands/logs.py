"""
Logs command
RESPONSIBILITY : Retrieve logs from the deployed services
"""


import sys

import typer

from weave_cli.docker.compose import DockerCompose , DockerComposeError
from weave_cli.docker.provider import LinuxDockerProvider, WindowsWslDockerProvider
from weave_cli.docker.runtime import DockerRuntime , DockerRuntimeError
from weave_cli.installation import InstallationManager , InstallationState, InstallationStateError
from weave_cli.platforms.linux import LinuxPlatform
from weave_cli.platforms.windows import WindowsPlatform


def logs(
    service : str | None = typer.Argument(
        None, help = "Service to view logs for (api, worker , postgres, redis, nginx)"
    ),

    follow : bool = typer.Option(
        False, "--follow", "-f", help = "Follow logs in real-time"
    )
):
    """View WEAVE CBT container logs"""


    if sys.platform == "win32":
        platform = WindowsPlatform(wsl_distribution = "WeaveCBT")
        provider = WindowsWslDockerProvider()
    elif sys.platform.startswith("linux"):
        platform = LinuxPlatform()
        provider = LinuxDockerProvider()
    else:
        typer.echo("[WEAVE][ERROR] Unsupported operating system.", err=True)
        raise typer.Exit(code=1)


    try:
        installation = InstallationManager(platform).load()


        compose = DockerCompose(
            compose_file = installation.install_directory / "compose.yaml",
            env_file = installation.install_directory / "runtime.env",
            runtime = DockerRuntime(provider)
        )


        result = compose.logs(service=service, follow=follow)

        if not follow:
            if result.stdout:
                typer.echo(result.stdout)
            if result.stderr:
                typer.echo(result.stderr, err=True)


    except (InstallationStateError , DockerComposeError , DockerRuntimeError) as exc:
        typer.echo(f"[WEAVE][ERROR] {str(exc)}", err=True)
        raise typer.Exit(code=1) from exc

def register(app : typer.Typer):
    """Register the logs command with the root CLI"""

    app.command(name = "logs")(logs)
