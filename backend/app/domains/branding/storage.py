"""Filesystem cache for the effective tenant logo used by the local CBT UI."""

from __future__ import annotations

import asyncio
import hashlib
import os
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx2 as httpx
from PIL import Image, UnidentifiedImageError

from app.core.settings import settings

ALLOWED_LOGO_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
MAX_LOGO_PIXELS = 20_000_000


class BrandingLogoStorageError(RuntimeError):
    """Raised when a remote school logo cannot be safely cached locally."""


@dataclass(frozen=True, slots=True)
class CachedBrandingLogo:
    storage_key: str
    mime_type: str
    size_bytes: int
    sha256: str


class BrandingLogoStorage:
    """Download, validate, and atomically cache school-logo bytes on local disk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or settings.BRANDING_LOGO_STORAGE_PATH).resolve()

    async def cache_from_url(
        self,
        *,
        url: str,
        tenant_id: UUID,
        revision: UUID,
    ) -> CachedBrandingLogo:
        data = await self._download(url)
        return await self.cache_bytes(
            data=data,
            tenant_id=tenant_id,
            revision=revision,
        )

    async def cache_bytes(
        self,
        *,
        data: bytes,
        tenant_id: UUID,
        revision: UUID,
    ) -> CachedBrandingLogo:
        """Validate bytes and atomically store one immutable logo revision."""

        if not data:
            raise BrandingLogoStorageError("School logo is empty.")
        if len(data) > settings.BRANDING_LOGO_MAX_SIZE_BYTES:
            raise BrandingLogoStorageError(
                "School logo exceeds the configured maximum size."
            )

        return await asyncio.to_thread(
            self._validate_and_store_sync,
            data,
            tenant_id,
            revision,
        )

    async def exists(self, storage_key: str) -> bool:
        path = self._resolve_storage_key(storage_key)
        return await asyncio.to_thread(path.is_file)

    async def read(self, storage_key: str) -> bytes:
        path = self._resolve_storage_key(storage_key)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, storage_key: str) -> None:
        path = self._resolve_storage_key(storage_key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def _download(self, url: str) -> bytes:
        parsed = urlsplit(str(url).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BrandingLogoStorageError("School logo URL must use HTTP or HTTPS.")

        timeout = httpx.Timeout(
            timeout=settings.WEAVE_REQUEST_TIMEOUT_SECONDS,
            connect=settings.WEAVE_CONNECT_TIMEOUT_SECONDS,
        )
        headers = {"Accept": "image/jpeg,image/png,image/webp"}

        try:
            async with (
                httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=True,
                    headers=headers,
                ) as client,
                client.stream("GET", url) as response,
            ):
                if not response.is_success:
                    raise BrandingLogoStorageError(
                        f"School logo download failed with HTTP {response.status_code}."
                    )

                content_length = response.headers.get("Content-Length")
                if (content_length and content_length.isdigit()) and (
                    int(content_length) > settings.BRANDING_LOGO_MAX_SIZE_BYTES
                ):
                    raise BrandingLogoStorageError(
                        "School logo exceeds the configured maximum size."
                    )

                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > settings.BRANDING_LOGO_MAX_SIZE_BYTES:
                        raise BrandingLogoStorageError(
                            "School logo exceeds the configured maximum size."
                        )
        except BrandingLogoStorageError:
            raise
        except httpx.TimeoutException as exc:
            raise BrandingLogoStorageError("School logo download timed out.") from exc
        except httpx.RequestError as exc:
            raise BrandingLogoStorageError(
                "School logo could not be downloaded."
            ) from exc

        if not buffer:
            raise BrandingLogoStorageError(
                "School logo download returned an empty file."
            )
        return bytes(buffer)

    def _validate_and_store_sync(
        self,
        data: bytes,
        tenant_id: UUID,
        revision: UUID,
    ) -> CachedBrandingLogo:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    image_format = image.format
                    if image_format not in ALLOWED_LOGO_FORMATS:
                        raise BrandingLogoStorageError(
                            "School logo must be JPEG, PNG, or WebP."
                        )
                    width, height = image.size
                    if width <= 0 or height <= 0 or width * height > MAX_LOGO_PIXELS:
                        raise BrandingLogoStorageError(
                            "School logo dimensions are invalid or too large."
                        )
                    image.verify()
        except BrandingLogoStorageError:
            raise
        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
        ) as exc:
            raise BrandingLogoStorageError(
                "Downloaded school logo is not a valid supported image."
            ) from exc

        mime_type, extension = ALLOWED_LOGO_FORMATS[image_format]
        sha256 = hashlib.sha256(data).hexdigest()
        storage_key = f"tenants/{tenant_id}/logo/{revision}{extension}"
        destination = self._resolve_storage_key(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(destination, data)

        return CachedBrandingLogo(
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=sha256,
        )

    def _resolve_storage_key(self, storage_key: str) -> Path:
        if not storage_key:
            raise BrandingLogoStorageError("School logo storage key is required.")

        relative = Path(storage_key)
        if relative.is_absolute():
            raise BrandingLogoStorageError("School logo storage key must be relative.")

        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root):
            raise BrandingLogoStorageError("Invalid school logo storage key.")
        return resolved

    @staticmethod
    def _atomic_write(destination: Path, data: bytes) -> None:
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


branding_logo_storage = BrandingLogoStorage()
