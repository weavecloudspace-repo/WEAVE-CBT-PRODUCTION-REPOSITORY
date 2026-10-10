"""Safely update a pinned CBT image with a matching PostgreSQL restore point."""

from __future__ import annotations

import re
from dataclasses import replace
from uuid import uuid4

import typer

from weave_cli.commands._shared import (
    COMMAND_ERRORS,
    banner,
    error,
    get_stack,
    info,
    save_runtime_env,
    success,
    warning,
)
from weave_cli.commands.install import _verify_started_stack, _assets_root, _read_release_manifest
from weave_cli.commands.update_recovery import (
    UpdateRecovery,
    guard_pending_update,
    mark_phase,
    read_recovery,
    recovery_path,
    save_recovery,
    update_lock,
)


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
    ending = (
        "\r\n"
        if lines[position].endswith("\r\n")
        else ("\n" if lines[position].endswith("\n") else "")
    )
    lines[position] = f"WEAVE_IMAGE={image}{ending}"
    return "".join(lines)


def _configured_image(env: str) -> str:
    lines = [line[len("WEAVE_IMAGE="):].strip() for line in env.splitlines()
             if line.startswith("WEAVE_IMAGE=")]
    if len(lines) != 1 or not lines[0]:
        raise ValueError("runtime.env must contain one nonempty WEAVE_IMAGE entry.")
    return lines[0]


def restore_previous(stack, record: UpdateRecovery) -> None:
    """Restore matching image and database; retain state if recovery fails.

    This may discard all school records created after the database snapshot.
    """
    journal = recovery_path(stack.installation.data_directory)
    stack.compose.stop_application()

    if record.phase in {"pending", "ready"}:
        stack.compose.restore_database(
            record.snapshot_database, record.failed_database
        )
        record = mark_phase(journal, record, "restored")

    env_file = stack.installation.data_directory / "runtime.env"
    current = env_file.read_text(encoding="utf-8")
    save_runtime_env(
        env_file,
        _replace_image(current, record.previous_image).encode("utf-8"),
    )
    stack.compose.start()
    _verify_started_stack(stack.runtime, stack.compose)
    stack.manager.update(
        replace(stack.installation, installed_version=record.previous_version)
    )

    # Cleanup is non-critical once the original API and DB are healthy.
    obsolete = (
        record.failed_database
        if record.phase == "restored"
        else record.snapshot_database
    )
    try:
        stack.compose.drop_snapshot_database(obsolete)
    except Exception as cleanup_error:
        warning(
            f"Previous CBT version restored; unused PostgreSQL database "
            f"{obsolete} remains for manual cleanup: {cleanup_error}"
        )
    journal.unlink(missing_ok=True)


def update(
    yes: bool = typer.Option(False, "--yes", help="Proceed without terminal prompt; caller must obtain explicit administrator confirmation."),
    image: str | None = typer.Option(
        None, "--image",
        help="Optional pinned image override; normally resolved from the packaged manager release.",
    ),
) -> None:
    """Upgrade a pinned CBT image/schema with a reversible database snapshot."""
    banner("Updating WEAVE CBT")
    try:
        if image is not None:
            _validate_image(image)
        stack = get_stack()
        if image is None:
            release = _read_release_manifest(_assets_root(None))
            if release is None:
                raise ValueError("This source manager has no release manifest; provide --image explicitly.")
            env = (stack.installation.data_directory / "runtime.env").read_text(encoding="utf-8")
            values = {}
            for line in env.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
            expected = "prod" if release["channel"] == "production" else "stg"
            if values.get("ENVIRONMENT") != expected or values.get("WEAVE_API_BASE_URL") != release["api"]:
                raise ValueError("Installed CBT environment does not match the manager's release channel or WEAVE API.")
            image = release["image"]
            info(f"Using image from {release['channel']} manager {release['version']}.")
        _validate_image(image)
        if not stack.platform.is_admin():
            raise PermissionError("Administrative privileges are required to update WEAVE CBT.")
        if not stack.runtime.docker_engine_running():
            raise RuntimeError("Docker Engine is not running. Run 'weave start' first.")

        data_dir = stack.installation.data_directory
        env_file = data_dir / "runtime.env"
        original = env_file.read_bytes()
        previous_image = _configured_image(original.decode("utf-8"))
        replacement = _replace_image(original.decode("utf-8"), image).encode("utf-8")
        if replacement == original:
            warning("The requested image is already configured.")
            return

        if not yes and not typer.confirm(
            "Update WEAVE CBT? Services will pause, and a database snapshot "
            "will be kept for image/schema rollback (extra disk space required).",
            default=False,
        ):
            warning("Update cancelled.")
            return

        with update_lock(data_dir):
            guard_pending_update(data_dir)
            journal = recovery_path(data_dir)
            old = read_recovery(journal)
            if old is not None:
                if old.target_image != previous_image:
                    raise RuntimeError(
                        "The configured image differs from the last rollback record. "
                        "Refusing to replace the saved database."
                    )
                # Only one restore point is retained. The previous snapshot
                # is pruned before a new snapshot is taken.
                stack.compose.drop_snapshot_database(old.snapshot_database)
                journal.unlink()

            token = uuid4().hex
            record = UpdateRecovery(
                previous_image=previous_image,
                target_image=image,
                previous_version=stack.installation.installed_version,
                snapshot_database=f"weave_cbt_rollback_{token}",
                failed_database=f"weave_cbt_failed_{token}",
            )
            save_recovery(journal, record)
            try:
                # Pull while the old API is still running. The journal blocks
                # unsafe subsequent starts if this update gets interrupted.
                save_runtime_env(env_file, replacement)
                stack.compose.config()
                info("Pulling the new pinned image...")
                stack.compose.pull_weave_image()

                info("Stopping CBT writers and snapshotting PostgreSQL...")
                stack.compose.stop_application()
                stack.compose.snapshot_database(record.snapshot_database)
                record = mark_phase(journal, record, "pending")

                info("Applying Alembic migrations in the one-shot bootstrap container...")
                stack.compose.start()
                _verify_started_stack(stack.runtime, stack.compose)

                stack.manager.update(replace(stack.installation, installed_version=image))
                mark_phase(journal, record, "ready")
            except Exception as upgrade_error:
                warning("Update failed; restoring the previous image and database...")
                try:
                    latest = read_recovery(journal)
                    if latest is None:
                        raise RuntimeError("Rollback journal was unexpectedly removed.")
                    restore_previous(stack, latest)
                    warning("Previous image AND database state restored.")
                except Exception as rollback_error:
                    error(
                        "AUTOMATIC ROLLBACK FAILED. Do not start CBT. "
                        "Recovery state and database snapshots were preserved. "
                        "Use 'weave rollback' after resolving the error. "
                        f"Cause: {rollback_error}"
                    )
                raise upgrade_error

        success(f"WEAVE CBT updated to {image}.")
        info(
            "A matching pre-update PostgreSQL snapshot is retained for 'weave rollback'. "
            "Rolling back later discards records written since this update."
        )
    except (*COMMAND_ERRORS, ValueError, RuntimeError, UnicodeError, PermissionError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command(name="update")(update)
