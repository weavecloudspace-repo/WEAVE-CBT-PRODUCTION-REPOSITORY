"""Durable local copy of effective Weave tenant branding."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BrandingState(Base):
    """Last effective light-mode branding received from Weave for this tenant."""

    __tablename__ = "branding_states"

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, unique=True, index=True)
    school_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Remote logo metadata is retained only when that exact revision has been
    # successfully cached locally. This makes logo_revision the effective local
    # logo version and guarantees the browser never depends on Weave at render time.
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_revision: Mapped[UUID | None] = mapped_column(nullable=True)
    logo_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    logo_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    logo_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_default_theme: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    theme_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    token_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    light_tokens: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "theme_version >= 0", name="ck_branding_states_theme_version_nonnegative"
        ),
        CheckConstraint(
            "token_schema_version >= 1",
            name="ck_branding_states_token_schema_version_positive",
        ),
        CheckConstraint(
            "logo_size_bytes IS NULL OR logo_size_bytes > 0",
            name="ck_branding_states_logo_size_positive",
        ),
        CheckConstraint(
            "(logo_storage_key IS NULL AND logo_mime_type IS NULL AND logo_size_bytes IS NULL AND logo_sha256 IS NULL) OR "
            "(logo_storage_key IS NOT NULL AND logo_mime_type IS NOT NULL AND logo_size_bytes IS NOT NULL AND logo_sha256 IS NOT NULL)",
            name="ck_branding_states_logo_cache_complete",
        ),
    )
