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

from weave_cli.main import main  # noqa: E402


if __name__ == "__main__":
    main()
