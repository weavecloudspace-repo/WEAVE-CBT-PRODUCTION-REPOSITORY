from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, HTTPException, Response, status

from app.core.database import DbSession
from app.domains.auth.coordination import LocalAuthCoordinationUnavailable
from app.domains.auth.dependencies import CurrentLocalContext
from app.domains.auth.models import WEAVE_AUTH_STATE_SYNCED
from app.domains.auth.schemas import (
    LocalActorResponse,
    StaffLoginRequest,
    StaffLoginResponse,
    StaffSessionResponse,
)
from app.domains.auth.service import (
    INVALID_LOCAL_STAFF_SESSION,
    LocalAuthService,
    LocalSessionAuthenticationError,
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

REFRESH_COOKIE_NAME = "weave_cbt_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(
    response: Response,
    token: str,
    *,
    expires_at: datetime,
) -> None:
    now = datetime.now(UTC)
    normalized_expiry = expires_at.astimezone(UTC)
    max_age = max(0, int((normalized_expiry - now).total_seconds()))
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,
        samesite="strict",
        max_age=max_age,
        expires=normalized_expiry,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=False,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _login_response(result) -> StaffLoginResponse:
    return StaffLoginResponse(
        access_token=result.access_token,
        access_token_expires_at=result.access_token_expires_at,
        session_expires_at=result.session_expires_at,
        cloud_auth_state=result.cloud_auth_state,
        actor=LocalActorResponse.model_validate(result.actor),
    )


@router.post(
    "/login",
    response_model=StaffLoginResponse,
    status_code=status.HTTP_200_OK,
)
async def login_staff(
    payload: StaffLoginRequest,
    response: Response,
    db: DbSession,
) -> StaffLoginResponse:
    result = await LocalAuthService.login_staff(db, payload=payload)
    _set_refresh_cookie(
        response,
        result.refresh_token,
        expires_at=result.session_expires_at,
    )
    return _login_response(result)


@router.post(
    "/refresh",
    response_model=StaffLoginResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_staff(
    response: Response,
    db: DbSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> StaffLoginResponse:
    if not refresh_token:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_LOCAL_STAFF_SESSION,
        )

    try:
        result = await LocalAuthService.refresh_staff(
            db,
            refresh_token=refresh_token,
            idempotency_key=idempotency_key,
        )
    except LocalSessionAuthenticationError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except LocalAuthCoordinationUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc

    _set_refresh_cookie(
        response,
        result.refresh_token,
        expires_at=result.session_expires_at,
    )
    return _login_response(result)


@router.get(
    "/session",
    response_model=StaffSessionResponse,
    status_code=status.HTTP_200_OK,
)
async def get_staff_session(
    context: CurrentLocalContext,
) -> StaffSessionResponse:
    now = datetime.now(UTC)
    session = context.session
    cloud_access_available = bool(
        session.weave_auth_state == WEAVE_AUTH_STATE_SYNCED
        and session.weave_access_token_expires_at is not None
        and session.weave_access_token_expires_at > now
    )
    return StaffSessionResponse(
        actor=LocalActorResponse.model_validate(context.actor),
        cloud_access_token_expires_at=session.weave_access_token_expires_at,
        session_expires_at=session.expires_at,
        cloud_auth_state=session.weave_auth_state,
        cloud_access_available=cloud_access_available,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout_staff(
    response: Response,
    db: DbSession,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> None:
    await LocalAuthService.logout_staff(db, refresh_token=refresh_token)
    _clear_refresh_cookie(response)
