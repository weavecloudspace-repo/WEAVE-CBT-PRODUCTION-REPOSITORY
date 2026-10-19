"""Entry point for standalone Nuitka CLI builds.

PowerShell 5.1 and redirected Windows console streams may default to cp1252,
which cannot encode the symbols in Typer/Rich and the WEAVE status banner.
Use UTF-8 before loading the CLI so official installer verification works
under both modern terminals and legacy Windows PowerShell.
"""
import sys


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        configure = getattr(stream, "reconfigure", None)
        if configure is not None:
            configure(encoding="utf-8", errors="backslashreplace")


_configure_console_encoding()

if __name__ == "__main__":
    from pathlib import Path
    from weave_cli.commands.client_resolution import CLIENT_WINDOWS, CLIENT_LINUX, main_client

    if Path(sys.argv[0]).name.casefold() in (CLIENT_WINDOWS.casefold(), CLIENT_LINUX):
        main_client()
    else:
        from weave_cli.main import main  # noqa: E402
        main()
