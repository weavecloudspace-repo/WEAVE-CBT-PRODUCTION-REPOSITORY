"""Fail-closed verification of explicitly purged WEAVE CBT Docker resources.

Never erase volumes by pattern: inspect only, and refuse installation when an
orphaned TLS certificate/HTTPS configuration volume could be reused.
"""

from __future__ import annotations

PROJECT_NAME = "weave-cbt"
TLS_VOLUMES = frozenset({
    "weave-cbt_tls_certificates",
    "weave-cbt_tls_snippets",
})


class PurgeSafetyError(RuntimeError):
    """WEAVE's destructive reset could not be verified as complete."""


def verify_purged_resources(runtime) -> None:
    """Require all WEAVE-labeled containers/volumes and known TLS names gone."""
    for args, description in (
        (["ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT_NAME}"], "containers"),
        (["volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={PROJECT_NAME}"], "volumes"),
        (["volume", "ls", "--format", "{{.Name}}"], "TLS volumes"),
    ):
        result = runtime.run_docker_command(args, timeout=30)
        if not result.successful or not isinstance(result.stdout, str):
            raise PurgeSafetyError(
                f"Cannot verify WEAVE {description} after purge; "
                "registration/installation cannot proceed safely."
            )
        if description != "TLS volumes":
            if result.stdout.strip():
                raise PurgeSafetyError(
                    f"WEAVE {description} remain after purge; "
                    "inspect Docker before installing a new server."
                )
        else:
            remaining = sorted(TLS_VOLUMES.intersection(result.stdout.splitlines()))
            if remaining:
                raise PurgeSafetyError(
                    "Previous WEAVE TLS certificate/configuration volumes remain: "
                    + ", ".join(remaining)
                    + ". Refusing to reuse them. Inspect Docker volume ownership manually."
                )
