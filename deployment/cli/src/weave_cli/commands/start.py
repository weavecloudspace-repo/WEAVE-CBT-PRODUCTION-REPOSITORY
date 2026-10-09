"""Start Docker Engine if needed, then start the WEAVE CBT Compose stack."""

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, fail, get_stack, info, success,
)


def start() -> None:
    """Start WEAVE CBT containers, preserving persistent data."""
    banner("Starting services")
    try:
        stack = get_stack()
        info("Ensuring persistent runtime startup...")
        stack.platform.ensure_runtime_persistence()
        if not stack.runtime.docker_engine_running():
            info("Starting Docker Engine...")
            stack.platform.start_docker_engine()
            if not stack.runtime.docker_engine_running():
                raise RuntimeError("Docker Engine did not become reachable.")

        info("Starting application containers...")
        stack.compose.start()
        success("Containers started. Use 'weave status' to inspect readiness.")
    except (*COMMAND_ERRORS, RuntimeError) as exc:
        fail(exc)


def register(app: typer.Typer) -> None:
    app.command(name="start")(start)
