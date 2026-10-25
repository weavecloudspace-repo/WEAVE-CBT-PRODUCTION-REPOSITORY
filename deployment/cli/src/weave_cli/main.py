"""Entry point for the WEAVE CBT local server management CLI."""

import typer

from weave_cli.commands import (
    network_prefer,
    network_ngrok,
    network_mode,
    network_runtime,
    doctor,
    install,
    lan,
    network,
    logs,
    restart,
    reinstall,
    self_update,
    release,
    rollback,
    start,
    status,
    tls,
    stop,
    uninstall,
    update,
)

app = typer.Typer(
    name="weave",
    help="WEAVE CBT — Local Server Management CLI",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)

# Each command module receives this same Typer app and registers its function.
for command in (
    install,
    lan,
    network,
    start,
    stop,
    restart,
    reinstall,
    self_update,
    status,
    tls,
    logs,
    doctor,
    release,
    update,
    rollback,
    uninstall,
):
    command.register(app)

# Extend the existing network command tree without duplicating its CLI app.
network_prefer.register(network.app)
network_ngrok.register(network.app)
network_mode.register(network.app)
network_runtime.register(network.app)


def main() -> None:
    """Run the CLI using the registered commands."""
    app()


if __name__ == "__main__":
    main()
