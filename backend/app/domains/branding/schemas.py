"""Local API schemas for CBT tenant branding."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BrandingResponse(BaseModel):
    """Effective local light-mode branding available to every CBT screen."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID | None = None
    school_name: str
    logo_revision: UUID | None = None
    logo_path: str | None = None
    is_enabled: bool = False
    is_default_theme: bool = True
    theme_version: int = Field(default=0, ge=0)
    token_schema_version: int = Field(default=4, ge=1)
    light_tokens: dict[str, str]
    is_synced: bool = False
