from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.media.models import MediaAsset
from app.domains.media.repository import MediaRepository
from app.domains.media.service import MediaService
from app.domains.media.storage import StoredMedia, local_media_storage


class MediaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_db_failure_rolls_back_and_removes_written_file(self) -> None:
        db = AsyncMock()
        actor = SimpleNamespace(id=uuid4(), role="teacher", is_active=True)
        stored = StoredMedia(
            storage_key="questions/aa/example.webp",
            mime_type="image/webp",
            size_bytes=120,
            sha256="a" * 64,
        )

        with (
            patch.object(
                local_media_storage,
                "save_question_image",
                new=AsyncMock(return_value=stored),
            ),
            patch.object(
                MediaRepository,
                "add_asset",
                new=AsyncMock(side_effect=RuntimeError("database failure")),
            ),
            patch.object(
                local_media_storage,
                "delete",
                new=AsyncMock(),
            ) as delete_file,
            self.assertRaisesRegex(RuntimeError, "database failure"),
        ):
            await MediaService.upload_question_image(
                db,
                actor=actor,  # type: ignore[arg-type]
                original_filename="diagram.png",
                data=b"image-bytes",
            )

        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
        delete_file.assert_awaited_once_with(stored.storage_key)

    async def test_referenced_asset_is_never_deleted(self) -> None:
        db = AsyncMock()
        asset = MediaAsset(
            id=uuid4(),
            storage_key="questions/aa/example.webp",
            original_filename="diagram.png",
            mime_type="image/webp",
            size_bytes=120,
            sha256="a" * 64,
            created_by_actor_id=uuid4(),
        )

        with (
            patch.object(
                MediaRepository,
                "get_asset_by_id",
                new=AsyncMock(return_value=asset),
            ) as get_asset,
            patch.object(
                MediaRepository,
                "is_referenced",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                MediaRepository,
                "delete_asset",
                new=AsyncMock(),
            ) as delete_asset,
            patch.object(
                local_media_storage,
                "delete",
                new=AsyncMock(),
            ) as delete_file,
            self.assertRaisesRegex(ValueError, "still referenced"),
        ):
            await MediaService.delete_unreferenced_asset(
                db,
                asset_id=asset.id,
            )

        get_asset.assert_awaited_once_with(db, asset.id, lock=True)
        delete_asset.assert_not_awaited()
        delete_file.assert_not_awaited()
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
