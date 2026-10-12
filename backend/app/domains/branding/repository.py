"""Persistence helpers for the local branding projection."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.branding.models import BrandingState


class BrandingRepository:
    @staticmethod
    async def get_for_tenant(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> BrandingState | None:
        result = await db.execute(
            select(BrandingState).where(BrandingState.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession,
        *,
        values: dict[str, Any],
    ) -> BrandingState:
        update_values = {
            key: value for key, value in values.items() if key != "tenant_id"
        }
        update_values["updated_at"] = func.now()

        statement = (
            insert(BrandingState)
            .values(id=uuid4(), **values)
            .on_conflict_do_update(
                index_elements=[BrandingState.tenant_id],
                set_=update_values,
            )
            .returning(BrandingState)
        )
        result = await db.execute(statement)
        return result.scalar_one()
