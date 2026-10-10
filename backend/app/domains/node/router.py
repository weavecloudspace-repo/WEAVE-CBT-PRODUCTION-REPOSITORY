# ========================== #
# app.domains.node.router
# ========================== #

from fastapi import APIRouter, HTTPException, Response, status

from app.core.database import DbSession
from app.domains.auth.dependencies import CurrentLocalAdmin
from app.domains.branding.service import branding_service
from app.domains.node.exceptions import (
    InstallationAlreadyPairedError,
    NodeIdentityStorageError,
)
from app.domains.node.schemas import (
    InstallationStatus,
    PairInstallationRequest,
    PairInstallationResponse,
)
from app.domains.node.service import node_service
from app.integrations.weave.exceptions import (
    WeaveContractError,
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)

router = APIRouter(
    prefix="/installation",
    tags=["Installation"],
)


@router.get(
    "/status",
    response_model=InstallationStatus,
)
def get_installation_status() -> InstallationStatus:
    return node_service.get_installation_status()


@router.post("/hostname/refresh", response_model=InstallationStatus)
async def refresh_installation_hostname(
    _admin: CurrentLocalAdmin,
) -> InstallationStatus:
    """Refresh the public DNS name using this installation's machine credential."""
    try:
        return await node_service.refresh_hostname()
    except WeaveUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="WEAVE Cloud is unreachable"
        ) from exc
    except WeaveRequestRejectedError as exc:
        raise HTTPException(
            status_code=502, detail="WEAVE rejected the hostname request"
        ) from exc
    except WeaveContractError as exc:
        raise HTTPException(
            status_code=502, detail="Invalid WEAVE hostname response"
        ) from exc


@router.post(
    "/pair",
    response_model=PairInstallationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def pair_installation(
    request: PairInstallationRequest,
    response: Response,
    db: DbSession,
) -> PairInstallationResponse:
    """Pair this local CBT runtime with a Weave tenant."""

    try:
        result = await node_service.pair_installation(request)
        # Branding is auxiliary. Pairing remains successful even if the
        # post-pair branding fetch cannot reach Weave; the default theme stays active.
        await branding_service.refresh_best_effort(db)
        return result

    except InstallationAlreadyPairedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except WeaveRequestRejectedError as exc:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            if exc.retry_after is not None:
                response.headers["Retry-After"] = str(exc.retry_after)

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=exc.detail,
                headers=(
                    {"Retry-After": str(exc.retry_after)}
                    if exc.retry_after is not None
                    else None
                ),
            ) from exc

        if 400 <= exc.status_code < 500:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Weave Cloud could not complete the pairing request.",
        ) from exc

    except WeaveUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Weave Cloud is currently unreachable.",
        ) from exc

    except WeaveContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=("Weave Cloud returned an unexpected pairing response."),
        ) from exc

    except NodeIdentityStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The CBT installation could not securely persist its local identity."
            ),
        ) from exc
