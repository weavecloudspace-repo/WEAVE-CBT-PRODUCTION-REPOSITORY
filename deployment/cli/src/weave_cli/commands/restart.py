"""Restart existing WEAVE CBT containers."""

import typer

from weave_cli.commands.update_recovery import guard_pending_update
from weave_cli.commands.lan import refresh_if_configured, LanError
from weave_cli.networking.deployment import apply as upgrade_deployment, DeploymentUpgradeError

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, fail, get_stack, info, success,
)


def restart() -> None:
    """Restart existing containers; use start after a full stop."""
    banner("Restarting services")
    try:
        stack = get_stack()
        guard_pending_update(stack.installation.data_directory)
        info("Ensuring persistent runtime startup...")
        stack.platform.ensure_runtime_persistence()
        if not stack.runtime.docker_engine_running():
            info("Starting Docker Engine...")
            stack.platform.start_docker_engine()
            if not stack.runtime.docker_engine_running():
                raise RuntimeError("Docker Engine did not become reachable.")

        deployment_changed = upgrade_deployment(stack)
        info("Applying deployed services..." if deployment_changed else "Restarting existing containers...")
        # Compose restart does not read changed configuration. The asset
        # upgrade used 'up -d'; normal explicit restart retains old semantics.
        if not deployment_changed:
            stack.compose.restart()
        refresh_if_configured(stack.installation.data_directory, runtime_type=stack.installation.runtime_type)
        success("Restart completed. Use 'weave status' to inspect readiness.")
    except (*COMMAND_ERRORS, RuntimeError, LanError, DeploymentUpgradeError) as exc:
        fail(exc)


def register(app: typer.Typer) -> None:
    app.command(name="restart")(restart)
