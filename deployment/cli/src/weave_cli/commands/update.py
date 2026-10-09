"""Update the pinned WEAVE CBT image using a best-effort rollback."""

from __future__ import annotations

import re
from dataclasses import replace

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS, banner, error, get_stack, info, save_runtime_env, success, warning,
)
from weave_cli.commands.install import _verify_started_stack


def _validate_image(image: str) -> None:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]*", image)
        or image.endswith(":latest")
        or not (":" in image.rsplit("/", 1)[-1] or "@sha256:" in image)
    ):
        raise ValueError("Use an explicitly versioned image tag or SHA256 digest.")


def _replace_image(env: str, image: str) -> str:
    lines = env.splitlines(keepends=True)
    indices = [i for i, line in enumerate(lines) if line.startswith("WEAVE_IMAGE=")]
    if len(indices) != 1:
        raise ValueError("runtime.env must contain exactly one WEAVE_IMAGE entry.")
    position = indices[0]
    ending = "\r\n" if lines[position].endswith("\r\n") else (
        "\n" if lines[position].endswith("\n") else ""
    )
    lines[position] = f"WEAVE_IMAGE={image}{ending}"
    return "".join(lines)


def update(
    image: str = typer.Option(..., "--image", help="New pinned WEAVE CBT image."),
) -> None:
    """Deploy a new application image; does not promise database rollback."""
    banner("Updating WEAVE CBT")
    try:
        _validate_image(image)
        stack = get_stack()
        if not stack.platform.is_admin():
            raise PermissionError("Administrative privileges are required to update WEAVE CBT.")
        if not stack.runtime.docker_engine_running():
            raise RuntimeError("Docker Engine is not running. Run 'weave start' first.")

        env_file = stack.installation.data_directory / "runtime.env"
        previous = env_file.read_bytes()
        replacement = _replace_image(previous.decode("utf-8"), image).encode("utf-8")
        if replacement == previous:
            warning("The requested image is already configured.")
            return

        if not typer.confirm(
            "Update WEAVE CBT? Database migrations may not be reversible.",
            default=False,
        ):
            warning("Update cancelled.")
            return

        info("Applying pinned image and pulling the new application image...")
        save_runtime_env(env_file, replacement)

        try:
            stack.compose.config()
            stack.compose.pull_weave_image()
            stack.compose.start()
            _verify_started_stack(stack.runtime, stack.compose)
            stack.manager.update(replace(stack.installation, installed_version=image))
        except Exception:
            warning("Update failed. Attempting to restore the previous image.")
            try:
                save_runtime_env(env_file, previous)
                stack.compose.start()
            except Exception as rollback_error:
                error(f"Container rollback also failed: {rollback_error}")
            raise

        success(f"WEAVE CBT updated to {image}.")
    except (*COMMAND_ERRORS, ValueError, RuntimeError, UnicodeError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="update")(update)
