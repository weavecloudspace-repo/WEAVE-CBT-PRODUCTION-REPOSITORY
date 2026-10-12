from __future__ import annotations

import os
import unittest
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.branding.service import (
    BrandingService,
    LogoCacheSnapshot,
)
from app.domains.branding.storage import BrandingLogoStorageError
from app.integrations.weave.branding import WeaveBrandingProjection


class _FakeLogoStorage:
    def __init__(self, *, exists: bool = True, fail_download: bool = False) -> None:
        self.file_exists = exists
        self.fail_download = fail_download
        self.download_calls = 0

    async def exists(self, _storage_key: str) -> bool:
        return self.file_exists

    async def cache_from_url(self, **_kwargs):
        self.download_calls += 1
        if self.fail_download:
            raise BrandingLogoStorageError("offline")
        raise AssertionError("cache_from_url should not be reached in this test")


def projection(*, logo_revision):
    return WeaveBrandingProjection.model_validate(
        {
            "tenant_id": str(uuid4()),
            "school_name": "Brightfield Academy",
            "logo_url": "https://cdn.example.test/logo.png",
            "logo_revision": str(logo_revision),
            "is_enabled": True,
            "is_default_theme": False,
            "theme_version": 2,
            "token_schema_version": 4,
            "light_tokens": {"--color-primary": "29 78 216"},
            "dark_tokens": {},
        }
    )


def cached_snapshot(revision):
    return LogoCacheSnapshot(
        logo_url="https://cdn.example.test/old-logo.png",
        logo_revision=revision,
        logo_storage_key=f"tenants/test/logo/{revision}.png",
        logo_mime_type="image/png",
        logo_size_bytes=123,
        logo_sha256="a" * 64,
    )


class BrandingLogoServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_revision_reuses_existing_local_logo_without_download(
        self,
    ) -> None:
        revision = uuid4()
        storage = _FakeLogoStorage(exists=True)
        service = BrandingService(logo_storage=storage)  # type: ignore[arg-type]

        values = await service._resolve_logo_values(
            projection=projection(logo_revision=revision),
            existing=cached_snapshot(revision),
        )

        self.assertEqual(values["logo_revision"], revision)
        self.assertEqual(storage.download_calls, 0)

    async def test_failed_new_logo_download_keeps_previous_valid_cache(self) -> None:
        old_revision = uuid4()
        new_revision = uuid4()
        storage = _FakeLogoStorage(exists=True, fail_download=True)
        service = BrandingService(logo_storage=storage)  # type: ignore[arg-type]

        values = await service._resolve_logo_values(
            projection=projection(logo_revision=new_revision),
            existing=cached_snapshot(old_revision),
        )

        self.assertEqual(values["logo_revision"], old_revision)
        self.assertEqual(storage.download_calls, 1)


if __name__ == "__main__":
    unittest.main()
