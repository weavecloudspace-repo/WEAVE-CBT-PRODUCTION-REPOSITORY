"""Append-only persistence operations for CBT audit events.

The repository records and reads audit history. It deliberately exposes no
update or delete operation because audit events are permanent records.
Transaction boundaries remain the responsibility of the calling service.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit.models import AuditActorType, AuditEvent, AuditOutcome


class AuditRepository:
    """Provide append-only database operations for audit history."""

    @staticmethod
    async def add_event(
        db: AsyncSession,
        event: AuditEvent,
    ) -> AuditEvent:
        """Add an audit event to the unit of work and flush it."""
        db.add(event)
        await db.flush()
        return event

    @staticmethod
    async def add_events(
        db: AsyncSession,
        events: Sequence[AuditEvent],
    ) -> list[AuditEvent]:
        """Add audit events and return the flushed rows."""
        rows = list(events)

        if not rows:
            return []

        db.add_all(rows)
        await db.flush()
        return rows

    @staticmethod
    async def get_event_by_id(
        db: AsyncSession,
        event_id: UUID,
    ) -> AuditEvent | None:
        """Return an audit event by local ID."""
        query = select(AuditEvent).where(AuditEvent.id == event_id)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_events(
        db: AsyncSession,
        *,
        actor_type: AuditActorType | None = None,
        actor_id: UUID | None = None,
        action: str | None = None,
        outcome: AuditOutcome | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        request_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AuditEvent]:
        """Return audit events matching the supplied indexed filters."""
        query = select(AuditEvent)

        if actor_type is not None:
            query = query.where(AuditEvent.actor_type == actor_type)

        if actor_id is not None:
            query = query.where(AuditEvent.actor_id == actor_id)

        if action is not None:
            query = query.where(AuditEvent.action == action)

        if outcome is not None:
            query = query.where(AuditEvent.outcome == outcome)

        if entity_type is not None:
            query = query.where(AuditEvent.entity_type == entity_type)

        if entity_id is not None:
            query = query.where(AuditEvent.entity_id == entity_id)

        if request_id is not None:
            query = query.where(AuditEvent.request_id == request_id)

        if created_from is not None:
            query = query.where(AuditEvent.created_at >= created_from)

        if created_to is not None:
            query = query.where(AuditEvent.created_at <= created_to)

        query = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())

        if offset:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        result = await db.execute(query)
        return list(result.scalars().all())
