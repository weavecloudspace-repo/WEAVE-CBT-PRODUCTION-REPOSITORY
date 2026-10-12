from __future__ import annotations

import asyncio
import hashlib
import os
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.settings import settings

CANVAS_WIDTH = 1200
CANVAS_HEIGHT = 900
MAX_UPSCALE_FACTOR = 2.0
MAX_SOURCE_PIXELS = 40_000_000

NORMALIZED_MIME_TYPE = "image/webp"
NORMALIZED_EXTENSION = ".webp"

ALLOWED_SOURCE_FORMATS = {
    "JPEG",
    "PNG",
    "WEBP",
}


@dataclass(frozen=True)
class StoredMedia:
    """Metadata for the exact normalized file written to local storage."""

    storage_key: str
    mime_type: str
    size_bytes: int
    sha256: str


class LocalMediaStorage:
    """Filesystem-only storage and normalization for immutable local CBT media."""

    def __init__(
        self,
        root: Path | None = None,
    ) -> None:
        self.root = (root or settings.MEDIA_STORAGE_PATH).resolve()

    async def save_question_image(
        self,
        data: bytes,
    ) -> StoredMedia:
        if not data:
            raise ValueError("Uploaded image is empty")

        if len(data) > settings.MEDIA_MAX_IMAGE_SIZE_BYTES:
            raise ValueError("Uploaded image exceeds the maximum allowed size")

        return await asyncio.to_thread(
            self._save_question_image_sync,
            data,
        )

    async def read(
        self,
        storage_key: str,
    ) -> bytes:
        path = self._resolve_storage_key(storage_key)
        return await asyncio.to_thread(path.read_bytes)

    async def exists(
        self,
        storage_key: str,
    ) -> bool:
        path = self._resolve_storage_key(storage_key)
        return await asyncio.to_thread(path.is_file)

    async def delete(
        self,
        storage_key: str,
    ) -> None:
        """Delete bytes only after MediaService has cleared reference safety."""

        path = self._resolve_storage_key(storage_key)
        await asyncio.to_thread(self._delete_sync, path)

    def _save_question_image_sync(
        self,
        data: bytes,
    ) -> StoredMedia:
        normalized_bytes = self._normalize_image(data)
        sha256 = hashlib.sha256(normalized_bytes).hexdigest()
        storage_key = self._generate_question_storage_key()
        destination = self._resolve_storage_key(storage_key)

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(destination, normalized_bytes)

        return StoredMedia(
            storage_key=storage_key,
            mime_type=NORMALIZED_MIME_TYPE,
            size_bytes=len(normalized_bytes),
            sha256=sha256,
        )

    @staticmethod
    def _normalize_image(
        data: bytes,
    ) -> bytes:
        """Normalize any accepted upload into a uniform 1200x900 WebP canvas.

        The source aspect ratio is always preserved. Large images are reduced,
        small images are enlarged by at most 2x, nothing is cropped or stretched,
        EXIF orientation is applied, transparency is composited onto white, and
        metadata is discarded by writing a new immutable WebP asset.
        """

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)

                with Image.open(BytesIO(data)) as source:
                    if source.format not in ALLOWED_SOURCE_FORMATS:
                        raise ValueError("Unsupported image format")

                    width, height = source.size
                    if width <= 0 or height <= 0:
                        raise ValueError("Image dimensions are invalid")
                    if width * height > MAX_SOURCE_PIXELS:
                        raise ValueError("Image dimensions are too large")

                    source = ImageOps.exif_transpose(source)
                    width, height = source.size

                    # Palette PNGs may carry transparency without an alpha band.
                    # Convert before resizing so their alpha is preserved correctly.
                    has_transparency = (
                        "A" in source.getbands() or "transparency" in source.info
                    )
                    working = source.convert("RGBA" if has_transparency else "RGB")

                    scale = min(
                        CANVAS_WIDTH / width,
                        CANVAS_HEIGHT / height,
                        MAX_UPSCALE_FACTOR,
                    )

                    target_width = max(1, round(width * scale))
                    target_height = max(1, round(height * scale))

                    resized = working.resize(
                        (target_width, target_height),
                        Image.Resampling.LANCZOS,
                    )

                    canvas = Image.new(
                        "RGB",
                        (CANVAS_WIDTH, CANVAS_HEIGHT),
                        "white",
                    )

                    x = (CANVAS_WIDTH - target_width) // 2
                    y = (CANVAS_HEIGHT - target_height) // 2

                    if resized.mode == "RGBA":
                        canvas.paste(resized, (x, y), resized)
                    else:
                        canvas.paste(resized, (x, y))

                    output = BytesIO()
                    canvas.save(
                        output,
                        format="WEBP",
                        lossless=True,
                        method=6,
                    )
                    return output.getvalue()

        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise ValueError("Uploaded file is not a valid supported image") from exc
        except OSError as exc:
            raise ValueError("Uploaded image could not be processed") from exc

    @staticmethod
    def _generate_question_storage_key() -> str:
        file_id = uuid4().hex
        return f"questions/{file_id[:2]}/{file_id}{NORMALIZED_EXTENSION}"

    def _resolve_storage_key(
        self,
        storage_key: str,
    ) -> Path:
        if not storage_key:
            raise ValueError("Storage key is required")

        relative_path = Path(storage_key)
        if relative_path.is_absolute():
            raise ValueError("Storage key must be relative")

        resolved = (self.root / relative_path).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Invalid storage key")

        return resolved

    @staticmethod
    def _atomic_write(
        destination: Path,
        data: bytes,
    ) -> None:
        """Write through a same-directory temporary file then atomically replace."""

        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")

        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _delete_sync(path: Path) -> None:
        path.unlink(missing_ok=True)


local_media_storage = LocalMediaStorage()
