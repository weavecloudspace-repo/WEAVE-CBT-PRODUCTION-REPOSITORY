"""FastAPI dependencies for locally issued staff access tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import DbSession
from app.core.security import InvalidLocalTokenError, decode_local_access_token
from app.domains.auth.models import LocalActor, LocalActorSession
from app.domains.auth.repository import AuthRepository
from app.domains.node.exceptions import NodeIdentityNotFoundError
from app.domains.node.identity_store import node_identity_store

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class LocalActorContext:
    actor: LocalActor
    session: LocalActorSession


async def get_current_local_context(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> LocalActorContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    try:
        payload = decode_local_access_token(credentials.credentials)
        session_id = UUID(str(payload["sid"]))
        identity = node_identity_store.load()
    except (
        InvalidLocalTokenError,
        ValueError,
        KeyError,
        NodeIdentityNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid local access token.",
        ) from exc

    if str(payload.get("installation_id")) != str(identity.server_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token belongs to another installation.",
        )

    # Authorization reads use the request-scoped AsyncSession, which means the
    # first SELECT would otherwise leave SQLAlchemy's implicit transaction open
    # for the rest of the route. Cloud-backed services intentionally open their
    # own short transactions around credential inspection/rotation and must not
    # inherit that read transaction. Keep the authorization lookup atomic and
    # finish it before returning control to the route.
    async with db.begin():
        session = await AuthRepository.get_session_by_id(db, session_id)
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= datetime.now(UTC)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Local session is not active.",
            )

        actor = await AuthRepository.get_actor_by_id(db, session.actor_id)
        if actor is None or not actor.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Local actor is not active.",
            )

        if actor.weave_actor_id != str(payload.get("sub")) or actor.role != payload.get(
            "role"
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token identity mismatch.",
            )

    return LocalActorContext(actor=actor, session=session)


async def get_current_local_actor(
    context: Annotated[LocalActorContext, Depends(get_current_local_context)],
) -> LocalActor:
    return context.actor


async def get_current_local_admin(
    actor: Annotated[LocalActor, Depends(get_current_local_actor)],
) -> LocalActor:
    if actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="School administrator access required.",
        )
    return actor


async def get_current_local_teacher(
    actor: Annotated[LocalActor, Depends(get_current_local_actor)],
) -> LocalActor:
    if actor.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teacher access required.",
        )
    return actor


CurrentLocalContext = Annotated[LocalActorContext, Depends(get_current_local_context)]
CurrentLocalActor = Annotated[LocalActor, Depends(get_current_local_actor)]
CurrentLocalAdmin = Annotated[LocalActor, Depends(get_current_local_admin)]
CurrentLocalTeacher = Annotated[LocalActor, Depends(get_current_local_teacher)]
