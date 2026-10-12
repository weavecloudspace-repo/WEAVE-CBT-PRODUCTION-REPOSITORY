from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from PIL import Image, ImageChops

from app.domains.media.storage import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    LocalMediaStorage,
)


def encoded_png(width: int, height: int, color: str) -> bytes:
    image = Image.new("RGB", (width, height), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def decode(data: bytes) -> Image.Image:
    image = Image.open(BytesIO(data))
    image.load()
    return image.convert("RGB")


def non_white_bounds(image: Image.Image):
    white = Image.new("RGB", image.size, "white")
    return ImageChops.difference(image, white).getbbox()


class MediaNormalizationTests(unittest.TestCase):
    def test_wide_image_is_contained_without_stretching(self) -> None:
        normalized = LocalMediaStorage._normalize_image(encoded_png(2000, 500, "red"))
        image = decode(normalized)

        self.assertEqual(image.size, (CANVAS_WIDTH, CANVAS_HEIGHT))
        self.assertEqual(non_white_bounds(image), (0, 300, 1200, 600))

    def test_portrait_image_is_contained_without_stretching(self) -> None:
        normalized = LocalMediaStorage._normalize_image(encoded_png(500, 2000, "blue"))
        image = decode(normalized)

        self.assertEqual(image.size, (CANVAS_WIDTH, CANVAS_HEIGHT))
        self.assertEqual(non_white_bounds(image), (487, 0, 712, 900))

    def test_tiny_image_is_never_upscaled_more_than_two_times(self) -> None:
        normalized = LocalMediaStorage._normalize_image(encoded_png(100, 100, "black"))
        image = decode(normalized)

        self.assertEqual(non_white_bounds(image), (500, 350, 700, 550))

    def test_storage_key_cannot_escape_media_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalMediaStorage(root=Path(directory))

            with self.assertRaisesRegex(ValueError, "Invalid storage key"):
                storage._resolve_storage_key("../../outside.webp")


class MediaStorageIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_hash_matches_exact_normalized_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalMediaStorage(root=Path(directory))

            stored = await storage.save_question_image(encoded_png(640, 480, "green"))
            data = await storage.read(stored.storage_key)

            self.assertEqual(stored.mime_type, "image/webp")
            self.assertEqual(stored.size_bytes, len(data))
            self.assertEqual(stored.sha256, hashlib.sha256(data).hexdigest())
            self.assertTrue(await storage.exists(stored.storage_key))

            await storage.delete(stored.storage_key)
            self.assertFalse(await storage.exists(stored.storage_key))


if __name__ == "__main__":
    unittest.main()
