"""Persistence for durable synchronization checkpoints."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sync.models import SyncState

# Transaction-scoped PostgreSQL advisory lock used to serialize application of
# Cloud -> CBT bootstrap/delta pages across every local API process. Network
# calls happen before this lock is acquired, so a slow Weave request never
# blocks unrelated local database work.
SYNC_ADVISORY_LOCK_KEY = 873_421_944


class SyncRepository:
    @staticmethod
    async def acquire_apply_lock(db: AsyncSession) -> None:
        """Serialize local synchronization writes for the current transaction."""
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": SYNC_ADVISORY_LOCK_KEY},
        )

    @staticmethod
    async def get_state(
        db: AsyncSession,
        scope: str,
        *,
        lock: bool = False,
    ) -> SyncState | None:
        query = select(SyncState).where(SyncState.scope == scope)
        if lock:
            query = query.with_for_update(of=SyncState)
        return (await db.execute(query)).scalar_one_or_none()

    @classmethod
    async def get_or_create_state(
        cls,
        db: AsyncSession,
        scope: str,
        *,
        lock: bool = False,
    ) -> SyncState:
        state = await cls.get_state(db, scope, lock=lock)
        if state is not None:
            return state
        state = SyncState(scope=scope)
        db.add(state)
        await db.flush()
        return state

    @staticmethod
    async def save_state(db: AsyncSession, state: SyncState) -> SyncState:
        db.add(state)
        await db.flush()
        return state
