"""Custom exceptions for the Weave Cloud integration boundary."""

from __future__ import annotations

from typing import Any


class WeaveIntegrationError(Exception):
    """Base exception for communication with Weave Cloud."""


class WeaveUnavailableError(WeaveIntegrationError):
    """Raised for timeout, DNS, connection, or equivalent transport failures."""


class WeaveRequestRejectedError(WeaveIntegrationError):
    """Raised when Weave receives a request but rejects it."""

    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        retry_after: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after
        self.payload = payload or {}
        super().__init__(detail)


class WeaveContractError(WeaveIntegrationError):
    """Raised when a successful Weave response violates the expected contract."""
