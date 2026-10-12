from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from PIL import Image

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core.settings import Settings
from app.domains.branding.storage import (
    BrandingLogoStorage,
    BrandingLogoStorageError,
)


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (32, 32), (29, 78, 216, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class BrandingLogoStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_logo_is_cached_under_tenant_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = BrandingLogoStorage(Path(temp_dir))
            tenant_id = uuid4()
            revision = uuid4()
            data = png_bytes()

            cached = await storage.cache_bytes(
                data=data,
                tenant_id=tenant_id,
                revision=revision,
            )

            self.assertEqual(
                cached.storage_key,
                f"tenants/{tenant_id}/logo/{revision}.png",
            )
            self.assertEqual(cached.mime_type, "image/png")
            self.assertEqual(cached.size_bytes, len(data))
            self.assertEqual(cached.sha256, hashlib.sha256(data).hexdigest())
            self.assertTrue(await storage.exists(cached.storage_key))
            self.assertEqual(await storage.read(cached.storage_key), data)

    async def test_invalid_image_bytes_are_rejected_without_creating_cache(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = BrandingLogoStorage(Path(temp_dir))

            with self.assertRaises(BrandingLogoStorageError):
                await storage.cache_bytes(
                    data=b"not-an-image",
                    tenant_id=uuid4(),
                    revision=uuid4(),
                )

            self.assertEqual(list(Path(temp_dir).rglob("*")), [])

    def test_logo_storage_path_is_runtime_configurable(self) -> None:
        self.assertIn("BRANDING_LOGO_STORAGE_PATH", Settings.model_fields)
        self.assertIn("BRANDING_LOGO_MAX_SIZE_BYTES", Settings.model_fields)


if __name__ == "__main__":
    unittest.main()
