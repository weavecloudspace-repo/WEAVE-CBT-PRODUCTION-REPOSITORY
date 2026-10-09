"""Entry point for the WEAVE CBT local server management CLI."""

import typer

from weave_cli.commands import (
    doctor,
    install,
    lan,
    logs,
    restart,
    release,
    rollback,
    start,
    status,
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
    start,
    stop,
    restart,
    status,
    logs,
    doctor,
    release,
    update,
    rollback,
    uninstall,
):
    command.register(app)


def main() -> None:
    """Run the CLI using the registered commands."""
    app()


if __name__ == "__main__":
    main()
