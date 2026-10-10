"""Opt-in certificate issuance for an already paired CBT server."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from weave_cli.commands._shared import COMMAND_ERRORS, banner, fail, get_stack, info, success
from weave_cli.commands.update_recovery import guard_pending_update


def tls(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate issuance with the Let's Encrypt staging CA."
    ),
    renew: bool = typer.Option(
        False, "--renew", help="Run certificate renewal now (normally automatic)."
    ),
    activate: bool = typer.Option(
        False, "--activate", help="Activate an already issued certificate without contacting ACME again."
    ),
) -> None:
    """Issue and maintain a browser-trusted certificate for this paired machine."""
    banner("HTTPS certificates")
    try:
        if int(dry_run) + int(renew) + int(activate) > 1:
            raise RuntimeError("--dry-run, --renew, and --activate cannot be combined")
        stack = get_stack()
        guard_pending_update(stack.installation.data_directory)
        if stack.installation.runtime_type == "wsl2" and not (dry_run or renew):
            if not stack.platform.is_admin():
                raise RuntimeError(
                    "Enable HTTPS from an elevated Administrator session so WEAVE "
                    "can configure the restricted Windows TCP/443 listener."
                )
            if not (stack.installation.data_directory / "lan.json").is_file():
                raise RuntimeError(
                    "Configure the trusted school LAN with 'weave lan' before enabling HTTPS."
                )
        if not stack.runtime.docker_engine_running():
            stack.platform.start_docker_engine()
        if not stack.runtime.docker_engine_running():
            raise RuntimeError("Docker Engine could not be started")
        marker = stack.installation.data_directory / "tls.enabled"
        if renew and not marker.is_file():
            raise RuntimeError("HTTPS has not been enabled. Run 'weave tls' first.")
        if not activate:
            command = ["--profile", "tls-issue", "run", "--rm", "--no-deps"]
            if dry_run:
                command.extend(["-e", "WEAVE_ACME_DRY_RUN=true"])
            command.append("certbot")
            if renew:
                command.append("renew")
            info("Contacting WEAVE Cloud to verify this school's assigned hostname...")
            stack.compose._run_compose_command(command=command, stream=True, timeout=None, stall_timeout=600)
            if dry_run:
                success("Certificate dry run passed; no trusted certificate installed.")
                return
        else:
            info("Validating the existing certificate and Nginx configuration; no reissuance.")
        if not renew:
            # Validate candidate HTTPS configuration in an ephemeral Nginx
            # container before changing the running stack or enabling renewal.
            stack.compose._run_compose_command(
                command=["run", "--rm", "--no-deps", "nginx", "nginx", "-t"]
            )
            # A marker is not a credential. A successful issuance enables the
            # renewal service on all subsequent start/restart commands.
            fd = (
                os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                if not marker.exists()
                else None
            )
            if fd is not None:
                try:
                    os.write(fd, b"enabled\n")
                    os.fsync(fd)
                finally:
                    os.close(fd)
        stack.compose.start()
        stack.compose._run_compose_command(
            command=["exec", "-T", "nginx", "nginx", "-t"]
        )
        stack.compose._run_compose_command(
            command=["exec", "-T", "nginx", "nginx", "-s", "reload"]
        )
        if stack.installation.runtime_type == "wsl2" and not renew:
            from weave_cli.commands.lan_tls import reconcile

            reconcile(stack.installation.data_directory)
        success("TLS is configured. Verify LAN DNS and HTTPS from another computer.")
    except (*COMMAND_ERRORS, RuntimeError, OSError) as exc:
        fail(exc)


def register(app: typer.Typer) -> None:
    app.command(name="tls")(tls)
