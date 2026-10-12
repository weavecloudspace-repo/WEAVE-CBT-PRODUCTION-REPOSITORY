from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from weave_cli.platforms.base import BasePlatform

INSTALLATION_SCHEMA_VERSION = 1


class InstallationStateError(RuntimeError):
    """Raised when WEAVE CBT installation state cannot be managed safely."""


@dataclass(frozen=True)
class InstallationState:
    """
    Persistent metadata describing an installed WEAVE CBT deployment.

    This state contains no secrets. Sensitive runtime configuration belongs
    in runtime.env, not install.json.
    """

    install_directory: Path
    data_directory: Path
    installed_version: str
    runtime_type: str
    installed_at: str
    schema_version: int = INSTALLATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "install_directory": str(self.install_directory),
            "data_directory": str(self.data_directory),
            "installed_version": self.installed_version,
            "runtime_type": self.runtime_type,
            "installed_at": self.installed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InstallationState:
        required_fields = {
            "schema_version",
            "install_directory",
            "data_directory",
            "installed_version",
            "runtime_type",
            "installed_at",
        }

        missing_fields = sorted(required_fields - payload.keys())

        if missing_fields:
            raise InstallationStateError(
                "Installation state is missing required field(s): "
                + ", ".join(missing_fields)
            )

        schema_version = payload["schema_version"]

        if not isinstance(schema_version, int):
            raise InstallationStateError(
                "Installation state field 'schema_version' must be an integer."
            )

        string_fields = (
            "install_directory",
            "data_directory",
            "installed_version",
            "runtime_type",
            "installed_at",
        )

        for field in string_fields:
            value = payload[field]

            if not isinstance(value, str) or not value.strip():
                raise InstallationStateError(
                    f"Installation state field '{field}' must be a non-empty string."
                )

        return cls(
            schema_version=schema_version,
            install_directory=Path(payload["install_directory"]),
            data_directory=Path(payload["data_directory"]),
            installed_version=payload["installed_version"].strip(),
            runtime_type=payload["runtime_type"].strip(),
            installed_at=payload["installed_at"].strip(),
        )


class InstallationManager:
    """
    Own the persistent machine-level WEAVE CBT installation state.

    The manager creates, loads, validates, updates, and removes install.json.
    It does not install, upgrade, repair, or uninstall WEAVE CBT itself.
    """

    def __init__(self, platform: BasePlatform) -> None:
        self.platform = platform

    @property
    def state_path(self) -> Path:
        return self.platform.installation_state_path

    def exists(self) -> bool:
        """Return True when the installation state file exists."""
        return self.state_path.is_file()

    def load(self) -> InstallationState:
        """
        Read install.json and return validated installation metadata.

        This validates the state structure and recorded installation paths.
        """
        if not self.exists():
            raise InstallationStateError(
                f"Installation state file '{self.state_path}' does not exist."
            )

        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InstallationStateError(
                f"Installation state file '{self.state_path}' contains invalid JSON."
            ) from exc
        except OSError as exc:
            raise InstallationStateError(
                f"Failed to read installation state file '{self.state_path}': {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise InstallationStateError(
                "Installation state must contain a JSON object."
            )

        state = InstallationState.from_dict(payload)
        self.validate(state)
        return state

    def create(self, state: InstallationState) -> None:
        """
        Create install.json for a newly completed installation.

        Refuses to overwrite an existing state file.
        """
        if self.exists():
            raise InstallationStateError(
                f"Installation state file '{self.state_path}' already exists."
            )

        self.validate(state)
        self._write_atomic(state)

    def update(self, state: InstallationState) -> None:
        """
        Replace existing installation metadata after an intentional lifecycle
        change such as an upgrade, repair, or supported migration.
        """
        if not self.exists():
            raise InstallationStateError(
                "Cannot update installation state because no installation "
                "state file exists."
            )

        self.validate(state)
        self._write_atomic(state)

    def validate(self, state: InstallationState) -> None:
        """
        Validate state schema and the filesystem locations it records.

        This does not inspect Docker, containers, services, or application
        health. Those belong to runtime diagnostics.
        """
        if state.schema_version != INSTALLATION_SCHEMA_VERSION:
            raise InstallationStateError(
                "Unsupported installation state schema version "
                f"'{state.schema_version}'. Expected "
                f"'{INSTALLATION_SCHEMA_VERSION}'."
            )

        if not state.installed_version.strip():
            raise InstallationStateError("Installed version cannot be empty.")

        if not state.runtime_type.strip():
            raise InstallationStateError("Runtime type cannot be empty.")

        try:
            datetime.fromisoformat(state.installed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InstallationStateError(
                "Installed timestamp must be a valid ISO 8601 timestamp."
            ) from exc

        if not state.install_directory.is_dir():
            raise InstallationStateError(
                f"Install directory '{state.install_directory}' does not exist."
            )

        if not state.data_directory.is_dir():
            raise InstallationStateError(
                f"Data directory '{state.data_directory}' does not exist."
            )

        compose_file = state.install_directory / "compose.yaml"

        if not compose_file.is_file():
            raise InstallationStateError(
                f"Compose file '{compose_file}' does not exist."
            )

        runtime_env = state.data_directory / "runtime.env"

        if not runtime_env.is_file():
            raise InstallationStateError(
                f"Runtime environment file '{runtime_env}' does not exist."
            )

    def delete(self) -> None:
        """
        Delete install.json.

        The caller is responsible for ensuring that the surrounding uninstall
        or reset workflow has completed successfully before calling this.
        """
        if not self.exists():
            return

        try:
            self.state_path.unlink()
        except OSError as exc:
            raise InstallationStateError(
                f"Failed to delete installation state file '{self.state_path}': {exc}"
            ) from exc

    def _write_atomic(self, state: InstallationState) -> None:
        """
        Write installation state atomically so an interrupted write cannot
        leave a partially written install.json.
        """
        parent = self.state_path.parent

        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InstallationStateError(
                f"Failed to create installation state directory '{parent}': {exc}"
            ) from exc

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=parent,
                prefix=f".{self.state_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(
                    state.to_dict(),
                    temporary_file,
                    indent=2,
                    sort_keys=True,
                )
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)

            os.replace(temporary_path, self.state_path)
        except OSError as exc:
            raise InstallationStateError(
                f"Failed to write installation state file '{self.state_path}': {exc}"
            ) from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
