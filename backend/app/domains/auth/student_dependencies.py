"""FastAPI dependencies for opaque student waiting-room and exam sessions."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status

from app.core.database import DbSession
from app.domains.auth.student_lifecycle_service import (
    StudentAuthenticationError,
    StudentAuthService,
    StudentSessionContext,
)

STUDENT_SESSION_COOKIE = "weave_cbt_student"


async def get_current_student_session(
    db: DbSession,
    raw_token: Annotated[str | None, Cookie(alias=STUDENT_SESSION_COOKIE)] = None,
) -> StudentSessionContext:
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student authentication required.",
        )
    try:
        context = await StudentAuthService.resolve_session(db, raw_token=raw_token)

        # Student session resolution performs database reads and may update
        # last_seen_at. When no touch is due, SQLAlchemy still leaves the
        # implicit read transaction open on the request-scoped AsyncSession.
        # Finish this dependency-owned unit of work before the route starts so
        # downstream services remain free to open their own explicit transaction.
        if db.in_transaction():
            await db.commit()

        return context
    except StudentAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


async def get_current_student_exam_session(
    context: Annotated[StudentSessionContext, Depends(get_current_student_session)],
) -> StudentSessionContext:
    if not context.is_exam_bound:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No examination is currently ready for this student.",
        )
    return context


CurrentStudentSession = Annotated[
    StudentSessionContext,
    Depends(get_current_student_session),
]

CurrentStudentExamSession = Annotated[
    StudentSessionContext,
    Depends(get_current_student_exam_session),
]
