"""Read-oriented persistence helpers for academic projection metadata."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.models import AssessmentComponent, AssessmentScheme


class AcademicQueryRepository:
    """Provide read-only projection queries used by academic query services."""

    @staticmethod
    async def list_assessment_schemes(
        db: AsyncSession,
        *,
        active_only: bool = True,
    ) -> list[AssessmentScheme]:
        query = select(AssessmentScheme).where(
            AssessmentScheme.source_deleted_at.is_(None)
        )
        if active_only:
            query = query.where(AssessmentScheme.status == "active")
        result = await db.execute(
            query.order_by(AssessmentScheme.name.asc(), AssessmentScheme.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_assessment_components(
        db: AsyncSession,
        *,
        assessment_scheme_id: UUID,
        active_only: bool = True,
    ) -> list[AssessmentComponent]:
        query = select(AssessmentComponent).where(
            AssessmentComponent.assessment_scheme_id == assessment_scheme_id,
            AssessmentComponent.source_deleted_at.is_(None),
        )
        if active_only:
            query = query.where(AssessmentComponent.is_active.is_(True))
        result = await db.execute(
            query.order_by(
                AssessmentComponent.position.asc(),
                AssessmentComponent.name.asc(),
                AssessmentComponent.id.asc(),
            )
        )
        return list(result.scalars().all())
