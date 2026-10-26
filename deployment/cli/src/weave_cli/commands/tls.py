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
    # Direct Python callers may leave this Typer OptionInfo default unset.
    activate = activate is True
    try:
        if int(dry_run) + int(renew) + int(activate) > 1:
            raise RuntimeError("--dry-run, --renew, and --activate cannot be combined")
        stack = get_stack()
        guard_pending_update(stack.installation.data_directory)
        wsl_transport = None
        if stack.installation.runtime_type == "wsl2" and not (dry_run or renew):
            if not stack.platform.is_admin():
                raise RuntimeError(
                    "Enable HTTPS from an elevated Administrator session so WEAVE "
                    "can configure the restricted Windows TCP/443 access."
                )
            from weave_cli.networking.state import load_or_import
            policy = load_or_import(
                stack.installation.data_directory, runtime_type="wsl2"
            )
            wsl_transport = policy["transport"]
            if wsl_transport == "mirrored":
                # Mirrored WSL exposes Docker ports directly; no NAT portproxy
                # or lan.json ownership file exists or should be created.
                # Validate the approved adapter and reconcile its scoped
                # Windows + Hyper-V rules *before* contacting the CA.
                from weave_cli.commands.network_mirrored import configure
                configure(stack, policy)
            elif wsl_transport == "nat":
                if not (stack.installation.data_directory / "lan.json").is_file():
                    raise RuntimeError(
                        "Configure the trusted school LAN with 'weave lan' "
                        "before enabling HTTPS in NAT mode."
                    )
            else:
                raise RuntimeError(
                    "Unsupported WSL network mode for TLS; inspect weave network mode status."
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
            # Nginx -t alone would also pass with no certificate and no TLS
            # server block. Verify both files and the generated vhost first.
            stack.compose._run_compose_command(command=[
                "run", "--rm", "--no-deps", "nginx", "sh", "-eu", "-c",
                "test -s /etc/letsencrypt/live/weave-cbt-node/fullchain.pem "
                "&& test -s /etc/letsencrypt/live/weave-cbt-node/privkey.pem "
                "&& test -s /etc/nginx/weave-conf/node.conf",
            ])
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
            if wsl_transport == "nat":
                from weave_cli.commands.lan_tls import reconcile

                reconcile(stack.installation.data_directory)
            # Mirrored mode already has scoped TCP/443 Windows and WSL Hyper-V
            # rules; creating a NAT portproxy here would be incorrect.
        # A previously opted-in DNS service follows the currently activated
        # HTTPS hostname. TLS never silently changes a school's router DNS.
        from weave_cli.commands.network_dns import reconcile_if_configured
        reconcile_if_configured(stack)
        success("TLS is configured. Verify LAN DNS and HTTPS from another computer.")
    except (*COMMAND_ERRORS, RuntimeError, OSError) as exc:
        fail(exc)


def register(app: typer.Typer) -> None:
    app.command(name="tls")(tls)
