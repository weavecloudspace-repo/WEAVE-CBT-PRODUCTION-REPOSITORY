"""Read-only WEAVE CBT installation and container status.

--json is an explicit, machine-readable contract for the desktop manager.
No passwords, environment contents or authorization tokens are included.
"""
from __future__ import annotations

import json
import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, fail, get_stack, info, success, warning,
)


def _container_rows(text: str) -> list[dict]:
    """Docker Compose JSON can be one array, one object, or NDJSON."""
    data = text.strip()
    if not data:
        return []
    try:
        parsed = json.loads(data)
        return [row for row in (parsed if isinstance(parsed, list) else [parsed])
                if isinstance(row, dict)]
    except json.JSONDecodeError:
        return [row for line in data.splitlines()
                for row in [json.loads(line)]
                if isinstance(row, dict)]


def _snapshot() -> dict:
    snapshot = {
        "schema": 1, "installed": False, "runtime": "unknown",
        "docker": False, "compose": False, "services": [],
        "running": False, "error": None,
    }
    try:
        stack = get_stack()
        snapshot["installed"] = True
        snapshot["installed_version"] = stack.installation.installed_version
        snapshot["runtime"] = stack.installation.runtime_type
        snapshot["docker"] = bool(stack.runtime.docker_engine_running())
        if not snapshot["docker"]:
            snapshot["error"] = "Docker Engine is not running."
            return snapshot
        snapshot["compose"] = bool(stack.runtime.docker_compose_available())
        if not snapshot["compose"]:
            snapshot["error"] = "Docker Compose is unavailable."
            return snapshot
        result = stack.compose._run_compose_command(command=["ps", "--all", "--format", "json"])
        for row in _container_rows(result.stdout):
            snapshot["services"].append({
                "name": str(row.get("Service") or row.get("Name") or "unknown"),
                "state": str(row.get("State") or "unknown").lower(),
                "health": str(row.get("Health") or "unknown").lower(),
                "exit_code": row.get("ExitCode"),
            })
        grouped = {}
        for item in snapshot["services"]:
            grouped.setdefault(item["name"], []).append(item)
        expected = ("api", "worker", "postgres", "redis", "nginx")
        snapshot["running"] = (
            all(grouped.get(name) for name in expected)
            and len(grouped.get("api", [])) >= 3
            and all(row["state"] == "running"
                    for name in expected for row in grouped.get(name, []))
            and all(row["health"] == "healthy"
                    for name in ("postgres", "redis")
                    for row in grouped.get(name, []))
            and bool(grouped.get("bootstrap"))
            and all(row["state"] == "exited" and str(row["exit_code"]) == "0"
                    for row in grouped.get("bootstrap", []))
        )
        if not snapshot["running"]:
            snapshot["error"] = "One or more CBT services are stopped or unavailable."
    except (*COMMAND_ERRORS, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        snapshot["error"] = str(exc)
    return snapshot


def status(
    json_output: bool = typer.Option(
        False, "--json", help="Emit one machine-readable JSON status document."
    ),
) -> None:
    """Show the installed version, Docker runtime and running containers."""
    if json_output:
        typer.echo(json.dumps(_snapshot(), separators=(",", ":"), ensure_ascii=True))
        return
    banner("System status")
    try:
        stack = get_stack()
        info(f"Installed version: {stack.installation.installed_version}")
        info(f"Runtime: {stack.installation.runtime_type}")
        if not stack.runtime.docker_engine_running():
            warning("Docker Engine is not running.")
            raise typer.Exit(code=1)
        success("Docker Engine is running.")
        if not stack.runtime.docker_compose_available():
            warning("Docker Compose is unavailable.")
            raise typer.Exit(code=1)
        success("Docker Compose is available.")
        result = stack.compose.status()
        typer.echo("\nContainers:")
        typer.echo(result.stdout or "No running containers.")
        if not result.stdout.strip():
            raise typer.Exit(code=1)
    except COMMAND_ERRORS as exc:
        fail(exc)


def register(app: typer.Typer) -> None:
    app.command(name="status")(status)
