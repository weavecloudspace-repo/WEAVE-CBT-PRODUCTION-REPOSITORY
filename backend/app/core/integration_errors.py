from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.integrations.weave.exceptions import (
    WeaveContractError,
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)

logger = logging.getLogger(__name__)

WEAVE_UNAVAILABLE_MESSAGE = (
    "Weave Cloud is currently unavailable. Check the internet connection and try again."
)
WEAVE_UPSTREAM_FAILURE_MESSAGE = "Weave Cloud could not complete the request. Try again, then contact support if it continues."
WEAVE_CONTRACT_FAILURE_MESSAGE = "Weave Cloud returned an unexpected response. Try again, then contact support if it continues."


async def weave_request_rejected_handler(
    request: Request,
    exc: WeaveRequestRejectedError,
) -> JSONResponse:
    """Expose safe upstream business/auth failures without turning them into 500s."""

    upstream_status = exc.status_code
    is_expected_client_failure = 400 <= upstream_status < 500
    response_status = (
        upstream_status if is_expected_client_failure else status.HTTP_502_BAD_GATEWAY
    )
    detail = (
        exc.detail if is_expected_client_failure else WEAVE_UPSTREAM_FAILURE_MESSAGE
    )

    log = logger.info if is_expected_client_failure else logger.warning
    log(
        "Weave rejected %s %s: upstream_status=%s detail=%s",
        request.method,
        request.url.path,
        upstream_status,
        exc.detail,
    )

    headers: dict[str, str] = {}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)

    content = {"detail": detail}
    if is_expected_client_failure:
        content.update(exc.payload)

    return JSONResponse(
        status_code=response_status,
        content=content,
        headers=headers,
    )


async def weave_unavailable_handler(
    request: Request,
    exc: WeaveUnavailableError,
) -> JSONResponse:
    """Translate Cloud connectivity failures into a user-actionable 503 response."""

    logger.warning(
        "Weave unavailable during %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": WEAVE_UNAVAILABLE_MESSAGE},
    )


async def weave_contract_error_handler(
    request: Request,
    exc: WeaveContractError,
) -> JSONResponse:
    """Hide integration-contract internals while preserving a distinct gateway failure."""

    logger.error(
        "Weave contract failure during %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": WEAVE_CONTRACT_FAILURE_MESSAGE},
    )


def register_weave_integration_error_handlers(app: FastAPI) -> None:
    """Install one application-wide translation boundary for Weave integration errors."""

    app.add_exception_handler(
        WeaveRequestRejectedError,
        weave_request_rejected_handler,
    )
    app.add_exception_handler(
        WeaveUnavailableError,
        weave_unavailable_handler,
    )
    app.add_exception_handler(
        WeaveContractError,
        weave_contract_error_handler,
    )
