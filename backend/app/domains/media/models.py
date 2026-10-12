# ==============================#
# backend.app.domains.media.model
# ==============================#


from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MEDIA_STORAGE_KEY_MAX_LENGTH = 512
MEDIA_FILENAME_MAX_LENGTH = 255
MEDIA_MIME_TYPE_MAX_LENGTH = 100
MEDIA_SHA256_LENGTH = 64


class MediaAsset(Base):
    """
    Metadata for a locally stored immutable media file.

    The database stores metadata and a relative storage key.
    The actual file bytes live on persistent local disk.
    """

    __tablename__ = "media_assets"

    storage_key: Mapped[str] = mapped_column(
        String(MEDIA_STORAGE_KEY_MAX_LENGTH),
        nullable=False,
        unique=True,
        index=True,
    )

    original_filename: Mapped[str] = mapped_column(
        String(MEDIA_FILENAME_MAX_LENGTH),
        nullable=False,
    )

    mime_type: Mapped[str] = mapped_column(
        String(MEDIA_MIME_TYPE_MAX_LENGTH),
        nullable=False,
    )

    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    sha256: Mapped[str] = mapped_column(
        String(MEDIA_SHA256_LENGTH),
        nullable=False,
        index=True,
    )

    created_by_actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "local_actors.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index(
            "ix_media_assets_mime_type_created",
            "mime_type",
            "created_at",
        ),
    )
