"""Persistence operations for durable CBT runtime infrastructure."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.runtime.models import (
    CBTRuntimeState,
    OutboxEventStatus,
    RealtimeOutboxEvent,
)


class RuntimeRepository:
    """Persist runtime heartbeats and transactional realtime outbox events."""

    @staticmethod
    async def add_runtime_state(
        db: AsyncSession,
        runtime: CBTRuntimeState,
    ) -> CBTRuntimeState:
        db.add(runtime)
        await db.flush()
        return runtime

    @staticmethod
    async def save_runtime_state(
        db: AsyncSession,
        runtime: CBTRuntimeState,
    ) -> CBTRuntimeState:
        db.add(runtime)
        await db.flush()
        return runtime

    @staticmethod
    async def get_runtime_state_by_id(
        db: AsyncSession,
        runtime_id: UUID,
        *,
        lock: bool = False,
    ) -> CBTRuntimeState | None:
        query = select(CBTRuntimeState).where(CBTRuntimeState.runtime_id == runtime_id)
        if lock:
            query = query.with_for_update(of=CBTRuntimeState)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_latest_runtime_state(
        db: AsyncSession,
        *,
        lock: bool = False,
    ) -> CBTRuntimeState | None:
        query = (
            select(CBTRuntimeState)
            .order_by(
                CBTRuntimeState.started_at.desc(),
                CBTRuntimeState.id.desc(),
            )
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=CBTRuntimeState)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_latest_ungraceful_runtime_before(
        db: AsyncSession,
        started_before: datetime,
        *,
        lock: bool = False,
    ) -> CBTRuntimeState | None:
        query = (
            select(CBTRuntimeState)
            .where(
                CBTRuntimeState.started_at < started_before,
                CBTRuntimeState.stopped_at.is_(None),
            )
            .order_by(
                CBTRuntimeState.started_at.desc(),
                CBTRuntimeState.id.desc(),
            )
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=CBTRuntimeState)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def add_outbox_event(
        db: AsyncSession,
        event: RealtimeOutboxEvent,
    ) -> RealtimeOutboxEvent:
        db.add(event)
        await db.flush()
        return event

    @staticmethod
    async def add_outbox_events(
        db: AsyncSession,
        events: Sequence[RealtimeOutboxEvent],
    ) -> list[RealtimeOutboxEvent]:
        rows = list(events)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def save_outbox_event(
        db: AsyncSession,
        event: RealtimeOutboxEvent,
    ) -> RealtimeOutboxEvent:
        db.add(event)
        await db.flush()
        return event

    @staticmethod
    async def get_outbox_event_by_id(
        db: AsyncSession,
        event_id: UUID,
        *,
        lock: bool = False,
    ) -> RealtimeOutboxEvent | None:
        query = select(RealtimeOutboxEvent).where(RealtimeOutboxEvent.id == event_id)
        if lock:
            query = query.with_for_update(of=RealtimeOutboxEvent)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_dispatchable_outbox_events(
        db: AsyncSession,
        *,
        available_at_or_before: datetime,
        statuses: Sequence[OutboxEventStatus] = (
            OutboxEventStatus.PENDING,
            OutboxEventStatus.FAILED,
        ),
        limit: int = 100,
        lock: bool = True,
        skip_locked: bool = True,
    ) -> list[RealtimeOutboxEvent]:
        status_values = list(statuses)
        if not status_values:
            return []

        query = (
            select(RealtimeOutboxEvent)
            .where(
                RealtimeOutboxEvent.status.in_(status_values),
                RealtimeOutboxEvent.available_at <= available_at_or_before,
            )
            .order_by(
                RealtimeOutboxEvent.available_at.asc(),
                RealtimeOutboxEvent.created_at.asc(),
                RealtimeOutboxEvent.id.asc(),
            )
            .limit(limit)
        )

        if lock:
            query = query.with_for_update(
                of=RealtimeOutboxEvent,
                skip_locked=skip_locked,
            )

        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_stale_publishing_events(
        db: AsyncSession,
        *,
        claimed_before: datetime,
        limit: int = 100,
        lock: bool = True,
        skip_locked: bool = True,
    ) -> list[RealtimeOutboxEvent]:
        query = (
            select(RealtimeOutboxEvent)
            .where(
                RealtimeOutboxEvent.status == OutboxEventStatus.PUBLISHING,
                RealtimeOutboxEvent.claimed_at.is_not(None),
                RealtimeOutboxEvent.claimed_at <= claimed_before,
            )
            .order_by(
                RealtimeOutboxEvent.claimed_at.asc(),
                RealtimeOutboxEvent.id.asc(),
            )
            .limit(limit)
        )

        if lock:
            query = query.with_for_update(
                of=RealtimeOutboxEvent,
                skip_locked=skip_locked,
            )

        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_outbox_events_for_aggregate(
        db: AsyncSession,
        *,
        aggregate_type: str,
        aggregate_id: UUID,
    ) -> list[RealtimeOutboxEvent]:
        result = await db.execute(
            select(RealtimeOutboxEvent)
            .where(
                RealtimeOutboxEvent.aggregate_type == aggregate_type,
                RealtimeOutboxEvent.aggregate_id == aggregate_id,
            )
            .order_by(
                RealtimeOutboxEvent.created_at.asc(),
                RealtimeOutboxEvent.id.asc(),
            )
        )
        return list(result.scalars().all())
