from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.models import LocalActor
from app.domains.media.models import MEDIA_FILENAME_MAX_LENGTH, MediaAsset
from app.domains.media.repository import MediaRepository
from app.domains.media.storage import local_media_storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaContent:
    """Physical media content returned after caller authorization."""

    data: bytes
    mime_type: str
    original_filename: str


def _normalize_original_filename(filename: str | None) -> str:
    """Keep the browser filename only as bounded metadata, never as a disk path."""

    if filename is None:
        return "image"

    filename = filename.strip().replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename:
        return "image"

    return filename[:MEDIA_FILENAME_MAX_LENGTH]


class MediaService:
    @staticmethod
    async def upload_question_image(
        db: AsyncSession,
        *,
        actor: LocalActor,
        original_filename: str | None,
        data: bytes,
    ) -> MediaAsset:
        """Normalize, persist and register one immutable local question image."""

        if not actor.is_active:
            raise ValueError("Active local actor is required")

        if actor.role not in {"admin", "teacher"}:
            raise ValueError("Only school staff may upload question media")

        filename = _normalize_original_filename(original_filename)
        stored = await local_media_storage.save_question_image(data)

        asset = MediaAsset(
            storage_key=stored.storage_key,
            original_filename=filename,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            created_by_actor_id=actor.id,
        )

        try:
            asset = await MediaRepository.add_asset(db, asset)
            await db.commit()
        except Exception:
            await db.rollback()

            try:
                await local_media_storage.delete(stored.storage_key)
            except Exception:
                logger.exception(
                    "Failed to remove orphaned media file %s after database persistence failure",
                    stored.storage_key,
                )

            raise

        return asset

    @staticmethod
    async def get_asset(
        db: AsyncSession,
        *,
        asset_id: UUID,
    ) -> MediaAsset:
        """Resolve metadata only; the caller owns question/exam authorization."""

        asset = await MediaRepository.get_asset_by_id(db, asset_id)
        if asset is None:
            raise ValueError("Media asset does not exist")
        return asset

    @staticmethod
    async def load_asset_content(
        db: AsyncSession,
        *,
        asset_id: UUID,
    ) -> MediaContent:
        """Load bytes for an asset whose domain-level access was already authorized."""

        asset = await MediaService.get_asset(db, asset_id=asset_id)

        try:
            data = await local_media_storage.read(asset.storage_key)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Media asset exists in the database but its physical file is missing"
            ) from exc

        return MediaContent(
            data=data,
            mime_type=asset.mime_type,
            original_filename=asset.original_filename,
        )

    @staticmethod
    async def delete_unreferenced_asset(
        db: AsyncSession,
        *,
        asset_id: UUID,
    ) -> bool:
        """Delete metadata and bytes only when no source or exam question references it.

        The MediaAsset row is locked before reference checks. This serializes cleanup
        against a concurrent question attachment that takes the same row lock.
        """

        asset = await MediaRepository.get_asset_by_id(
            db,
            asset_id,
            lock=True,
        )

        if asset is None:
            return False

        if await MediaRepository.is_referenced(db, asset.id):
            raise ValueError("Media asset is still referenced and cannot be deleted")

        storage_key = asset.storage_key

        try:
            await MediaRepository.delete_asset(db, asset)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "Media asset became referenced and cannot be deleted"
            ) from exc
        except Exception:
            await db.rollback()
            raise

        # DB metadata is removed first. If disk deletion fails, the safe failure mode
        # is an orphaned file rather than a Question/ExamQuestion with missing bytes.
        try:
            await local_media_storage.delete(storage_key)
        except Exception:
            logger.exception(
                "Media metadata was deleted but physical file %s could not be removed",
                storage_key,
            )

        return True
