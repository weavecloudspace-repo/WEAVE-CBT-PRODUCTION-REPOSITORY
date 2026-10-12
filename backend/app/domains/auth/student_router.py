"""Student CBT authentication and waiting-room routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from app.core.database import DbSession
from app.domains.auth.student_dependencies import STUDENT_SESSION_COOKIE
from app.domains.auth.student_lifecycle_service import (
    INVALID_STUDENT_LOGIN,
    StudentAuthenticationError,
    StudentAuthService,
)
from app.domains.auth.student_schemas import (
    StudentLoginRequest,
    StudentLoginResponse,
    StudentSessionResponse,
)

router = APIRouter(prefix="/student/auth", tags=["Student Authentication"])


def _auth_error(exc: StudentAuthenticationError) -> HTTPException:
    detail = str(exc)
    code = (
        status.HTTP_401_UNAUTHORIZED
        if detail == INVALID_STUDENT_LOGIN or "session" in detail.lower()
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=code, detail=detail)


@router.post("/login", response_model=StudentLoginResponse)
async def login_student(
    payload: StudentLoginRequest,
    response: Response,
    db: DbSession,
) -> StudentLoginResponse:
    try:
        result = await StudentAuthService.login(
            db,
            admission_number=payload.admission_number,
            password=payload.password,
        )
    except StudentAuthenticationError as exc:
        raise _auth_error(exc) from exc

    response.set_cookie(
        key=STUDENT_SESSION_COOKIE,
        value=result.raw_token,
        httponly=True,
        secure=False,
        samesite="strict",
        max_age=8 * 60 * 60,
        path="/api/v1/student",
    )
    return result.response


@router.get("/status", response_model=StudentSessionResponse)
async def get_student_waiting_room_status(
    db: DbSession,
    raw_token: Annotated[str | None, Cookie(alias=STUDENT_SESSION_COOKIE)] = None,
) -> StudentSessionResponse:
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student authentication required.",
        )
    try:
        return await StudentAuthService.get_waiting_room_status(
            db,
            raw_token=raw_token,
        )
    except StudentAuthenticationError as exc:
        raise _auth_error(exc) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_student(
    response: Response,
    db: DbSession,
    raw_token: Annotated[str | None, Cookie(alias=STUDENT_SESSION_COOKIE)] = None,
) -> None:
    if raw_token:
        await StudentAuthService.logout(db, raw_token=raw_token)
    response.delete_cookie(
        key=STUDENT_SESSION_COOKIE,
        path="/api/v1/student",
        samesite="strict",
    )
