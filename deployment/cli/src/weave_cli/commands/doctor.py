"""Read-only operational diagnostics for a WEAVE CBT installation."""

import typer
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from weave_cli.commands.lan import _read_state, _mapped_destination, _firewall_exists, _verify_firewall, LanError

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, error, get_stack, info, success, warning,
)


def _probe_local_http() -> None:
    """Check Nginx/browser routes without altering the installation."""
    for route in ("staff", "student"):
        url = f"http://127.0.0.1/{route}"
        try:
            with urlopen(url, timeout=5) as response:
                if not 200 <= response.status < 400:
                    raise RuntimeError(f"{url} returned HTTP {response.status}.")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"Local browser endpoint {url} is unreachable: {exc}. "
                "Inspect 'weave logs nginx' and container health."
            ) from exc


def doctor() -> None:
    """Check installation state, Docker, Compose and container availability."""
    banner("System diagnostics")
    try:
        stack = get_stack()
        success("Installation state and deployment files are valid.")

        for available, description in (
            (stack.runtime.docker_cli_available(), "Docker CLI"),
            (stack.runtime.docker_engine_running(), "Docker Engine"),
            (stack.runtime.docker_compose_available(), "Compose plugin"),
        ):
            if not available:
                error(f"{description} is unavailable.")
                raise typer.Exit(code=1)
            success(f"{description} is available.")

        stack.compose.config()
        success("Compose configuration is valid.")

        result = stack.compose.status()
        info("Running containers:")
        typer.echo(result.stdout or "None")
        if not result.stdout.strip():
            warning("No running containers detected.")
            raise typer.Exit(code=1)

        _probe_local_http()
        success("Both staff and student HTTP endpoints respond locally.")

        if stack.installation.runtime_type == "wsl2":
            state = _read_state(stack.installation.data_directory)
            if state is not None:
                destination = _mapped_destination(state["listen_address"])
                if destination != f'{state["wsl_address"]}/80' or not _firewall_exists():
                    raise RuntimeError(
                        "Saved LAN forwarding differs from Windows networking. "
                        "Run 'weave lan --refresh' in elevated PowerShell."
                    )
                _verify_firewall(state["listen_address"], state["client_subnet"])
                info(f"Configured school LAN address: {state['listen_address']} "
                     f"(clients: {state['client_subnet']}).")
            else:
                warning("School LAN forwarding is not yet configured; use 'weave lan' to opt in.")
            warning(
                "Windows localhost readiness is not proof of student LAN access. "
                "Test from a separate student computer."
            )
        else:
            info("Confirm the CBT endpoint is reachable from another computer on the school LAN.")

        success("Basic diagnostics complete. Check container health separately.")
    except (*COMMAND_ERRORS, RuntimeError, LanError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="doctor")(doctor)
