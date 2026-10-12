"""Persistence operations for local authentication data.

The repository only reads and writes SQLAlchemy models. Authentication rules,
token rotation, revocation decisions, and transaction boundaries belong to the
auth service.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.models import (
    LocalActor,
    LocalActorSession,
    LocalRefreshToken,
)


class AuthRepository:
    """Provide database operations for actors and their local sessions."""

    @staticmethod
    async def add_actor(
        db: AsyncSession,
        actor: LocalActor,
    ) -> LocalActor:
        """Add an actor to the unit of work and flush pending changes."""
        db.add(actor)
        await db.flush()
        return actor

    @staticmethod
    async def get_actor_by_id(
        db: AsyncSession,
        actor_id: UUID,
        *,
        lock: bool = False,
    ) -> LocalActor | None:
        """Return an actor by local ID, optionally locking its row."""
        query = select(LocalActor).where(LocalActor.id == actor_id)

        if lock:
            query = query.with_for_update()

        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_actor_by_weave_identity(
        db: AsyncSession,
        weave_actor_id: str,
        role: str,
        *,
        lock: bool = False,
    ) -> LocalActor | None:
        """Return the actor matching a Weave actor ID and role."""
        query = select(LocalActor).where(
            LocalActor.weave_actor_id == weave_actor_id,
            LocalActor.role == role,
        )

        if lock:
            query = query.with_for_update()

        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_actor_by_membership_id(
        db: AsyncSession,
        weave_membership_id: str,
        *,
        lock: bool = False,
    ) -> LocalActor | None:
        """Return an actor by its unique Weave membership ID."""
        query = select(LocalActor).where(
            LocalActor.weave_membership_id == weave_membership_id,
        )

        if lock:
            query = query.with_for_update()

        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_actors_by_email(
        db: AsyncSession,
        email: str,
        *,
        role: str | None = None,
        active_only: bool = False,
    ) -> list[LocalActor]:
        """Return actors with an email address, optionally filtered by role."""
        query = select(LocalActor).where(LocalActor.email == email)

        if role is not None:
            query = query.where(LocalActor.role == role)

        if active_only:
            query = query.where(LocalActor.is_active.is_(True))

        result = await db.execute(
            query.order_by(LocalActor.role.asc(), LocalActor.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_actors(
        db: AsyncSession,
        *,
        role: str | None = None,
        active_only: bool = False,
    ) -> list[LocalActor]:
        """Return local actors, optionally filtered by role and active state."""
        query = select(LocalActor)

        if role is not None:
            query = query.where(LocalActor.role == role)

        if active_only:
            query = query.where(LocalActor.is_active.is_(True))

        result = await db.execute(
            query.order_by(LocalActor.display_name.asc(), LocalActor.email.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def save_actor(
        db: AsyncSession,
        actor: LocalActor,
    ) -> LocalActor:
        """Attach an actor to the unit of work and flush pending changes."""
        db.add(actor)
        await db.flush()
        return actor

    @staticmethod
    async def add_session(
        db: AsyncSession,
        actor_session: LocalActorSession,
    ) -> LocalActorSession:
        """Add an actor session and flush pending changes."""
        db.add(actor_session)
        await db.flush()
        return actor_session

    @staticmethod
    async def get_session_by_id(
        db: AsyncSession,
        session_id: UUID,
        *,
        lock: bool = False,
    ) -> LocalActorSession | None:
        """Return an actor session by ID, optionally locking its row."""
        query = select(LocalActorSession).where(
            LocalActorSession.id == session_id,
        )

        if lock:
            query = query.with_for_update()

        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_sessions_for_actor(
        db: AsyncSession,
        actor_id: UUID,
        *,
        include_revoked: bool = False,
        lock: bool = False,
    ) -> list[LocalActorSession]:
        """Return an actor's sessions, newest first, optionally row-locked."""
        query = select(LocalActorSession).where(
            LocalActorSession.actor_id == actor_id,
        )

        if not include_revoked:
            query = query.where(LocalActorSession.revoked_at.is_(None))

        if lock:
            query = query.with_for_update(of=LocalActorSession)

        result = await db.execute(query.order_by(LocalActorSession.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def save_session(
        db: AsyncSession,
        actor_session: LocalActorSession,
    ) -> LocalActorSession:
        """Attach an actor session to the unit of work and flush changes."""
        db.add(actor_session)
        await db.flush()
        return actor_session

    @staticmethod
    async def add_refresh_token(
        db: AsyncSession,
        refresh_token: LocalRefreshToken,
    ) -> LocalRefreshToken:
        """Add a refresh-token fingerprint and flush pending changes."""
        db.add(refresh_token)
        await db.flush()
        return refresh_token

    @staticmethod
    async def get_refresh_token_by_id(
        db: AsyncSession,
        refresh_token_id: UUID,
        *,
        lock: bool = False,
    ) -> LocalRefreshToken | None:
        """Return a refresh token by ID, optionally locking its row."""
        query = select(LocalRefreshToken).where(
            LocalRefreshToken.id == refresh_token_id,
        )

        if lock:
            query = query.with_for_update()

        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_refresh_token_by_hash(
        db: AsyncSession,
        token_hash: str,
        *,
        lock: bool = False,
    ) -> LocalRefreshToken | None:
        """Return a refresh token by its stored fingerprint."""
        query = select(LocalRefreshToken).where(
            LocalRefreshToken.token_hash == token_hash,
        )

        if lock:
            query = query.with_for_update()

        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_refresh_tokens_for_session(
        db: AsyncSession,
        session_id: UUID,
        *,
        include_revoked: bool = False,
        lock: bool = False,
    ) -> list[LocalRefreshToken]:
        """Return refresh tokens issued for a session, optionally row-locked."""
        query = select(LocalRefreshToken).where(
            LocalRefreshToken.session_id == session_id,
        )

        if not include_revoked:
            query = query.where(LocalRefreshToken.revoked_at.is_(None))

        if lock:
            query = query.with_for_update(of=LocalRefreshToken)

        result = await db.execute(query.order_by(LocalRefreshToken.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def save_refresh_token(
        db: AsyncSession,
        refresh_token: LocalRefreshToken,
    ) -> LocalRefreshToken:
        """Attach a refresh token to the unit of work and flush changes."""
        db.add(refresh_token)
        await db.flush()
        return refresh_token

    @staticmethod
    async def save_refresh_tokens(
        db: AsyncSession,
        refresh_tokens: Sequence[LocalRefreshToken],
    ) -> list[LocalRefreshToken]:
        """Attach refresh tokens and return the flushed rows."""
        rows = list(refresh_tokens)

        if not rows:
            return []

        db.add_all(rows)
        await db.flush()
        return rows
