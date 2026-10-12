"""Resolve, validate, and refresh the local Weave branding projection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.domains.branding.models import BrandingState
from app.domains.branding.repository import BrandingRepository
from app.domains.branding.schemas import BrandingResponse
from app.domains.branding.storage import (
    BrandingLogoStorage,
    BrandingLogoStorageError,
    branding_logo_storage,
)
from app.domains.node.exceptions import NodeIdentityNotFoundError
from app.domains.node.identity_store import node_identity_store
from app.integrations.weave.branding import (
    WeaveBrandingGateway,
    WeaveBrandingProjection,
    weave_branding_gateway,
)

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_SCHEMA_VERSION = 4
DEFAULT_LIGHT_TOKENS: dict[str, str] = {
    "--color-primary": "29 78 216",
    "--color-primary-hover": "30 64 175",
    "--color-primary-soft": "239 246 255",
    "--color-primary-subtle": "248 250 252",
    "--color-primary-deep": "30 58 138",
    "--color-on-primary": "255 255 255",
    "--color-accent": "79 70 229",
    "--color-accent-hover": "67 56 202",
    "--color-accent-soft": "238 242 255",
    "--color-on-accent": "255 255 255",
    "--color-background": "248 250 252",
    "--color-surface": "255 255 255",
    "--color-surface-raised": "255 255 255",
    "--color-surface-muted": "248 250 252",
    "--color-surface-subtle": "241 245 249",
    "--color-border": "226 232 240",
    "--color-border-strong": "203 213 225",
    "--color-border-subtle": "241 245 249",
    "--color-text": "15 23 42",
    "--color-text-soft": "51 65 85",
    "--color-text-muted": "100 116 139",
    "--color-text-faint": "148 163 184",
    "--color-text-inverse": "255 255 255",
    "--color-sidebar-background": "255 255 255",
    "--color-sidebar-text": "15 23 42",
    "--color-sidebar-active": "29 78 216",
    "--color-sidebar-active-text": "255 255 255",
    "--color-sidebar-border": "226 232 240",
    "--color-header-background": "255 255 255",
    "--color-header-text": "15 23 42",
    "--color-header-text-muted": "100 116 139",
    "--color-header-surface": "248 250 252",
    "--color-header-surface-hover": "241 245 249",
    "--color-header-border": "226 232 240",
    "--color-focus-ring": "29 78 216",
}
SUPPORTED_LIGHT_TOKEN_KEYS = frozenset(DEFAULT_LIGHT_TOKENS)


class BrandingContractError(RuntimeError):
    """Raised when Weave branding cannot be safely projected locally."""


@dataclass(frozen=True, slots=True)
class LocalBrandingLogo:
    content: bytes
    mime_type: str
    sha256: str
    revision: UUID


@dataclass(frozen=True, slots=True)
class LogoCacheSnapshot:
    logo_url: str | None
    logo_revision: UUID | None
    logo_storage_key: str | None
    logo_mime_type: str | None
    logo_size_bytes: int | None
    logo_sha256: str | None


class BrandingService:
    def __init__(
        self,
        gateway: WeaveBrandingGateway = weave_branding_gateway,
        logo_storage: BrandingLogoStorage = branding_logo_storage,
    ) -> None:
        self.gateway = gateway
        self.logo_storage = logo_storage

    @staticmethod
    def _normalize_channel_value(key: str, value: str) -> str:
        parts = str(value).strip().split()
        if len(parts) != 3:
            raise BrandingContractError(f"Invalid RGB branding token for {key}.")
        try:
            channels = tuple(int(part) for part in parts)
        except ValueError as exc:
            raise BrandingContractError(
                f"Invalid RGB branding token for {key}."
            ) from exc
        if any(channel < 0 or channel > 255 for channel in channels):
            raise BrandingContractError(f"Invalid RGB branding token for {key}.")
        return " ".join(str(channel) for channel in channels)

    @classmethod
    def normalize_light_tokens(cls, tokens: dict[str, str]) -> dict[str, str]:
        """Overlay only known semantic tokens on top of the built-in Weave theme."""

        normalized = dict(DEFAULT_LIGHT_TOKENS)
        for key, value in tokens.items():
            if key not in SUPPORTED_LIGHT_TOKEN_KEYS:
                continue
            normalized[key] = cls._normalize_channel_value(key, value)
        return normalized

    @staticmethod
    def _default_response(
        *,
        tenant_id: UUID | None = None,
        school_name: str = "Weave CBT",
    ) -> BrandingResponse:
        return BrandingResponse(
            tenant_id=tenant_id,
            school_name=school_name,
            light_tokens=dict(DEFAULT_LIGHT_TOKENS),
            token_schema_version=DEFAULT_TOKEN_SCHEMA_VERSION,
            is_synced=False,
        )

    @staticmethod
    def _response_from_state(state: BrandingState) -> BrandingResponse:
        logo_path = None
        if state.logo_revision is not None and state.logo_storage_key:
            prefix = settings.API_V1_PREFIX.rstrip("/")
            logo_path = f"{prefix}/branding/logo?v={state.logo_revision}"

        return BrandingResponse(
            tenant_id=state.tenant_id,
            school_name=state.school_name,
            logo_revision=state.logo_revision,
            logo_path=logo_path,
            is_enabled=state.is_enabled,
            is_default_theme=state.is_default_theme,
            theme_version=state.theme_version,
            token_schema_version=state.token_schema_version,
            light_tokens=dict(state.light_tokens),
            is_synced=True,
        )

    async def get_effective(self, db: AsyncSession) -> BrandingResponse:
        """Read local branding only; this endpoint never depends on Cloud availability."""

        try:
            identity = node_identity_store.load()
        except NodeIdentityNotFoundError:
            return self._default_response()

        state = await BrandingRepository.get_for_tenant(db, identity.tenant_id)
        if state is None:
            return self._default_response(
                tenant_id=identity.tenant_id,
                school_name=identity.tenant_name,
            )
        return self._response_from_state(state)

    async def get_cached_logo(self, db: AsyncSession) -> LocalBrandingLogo | None:
        """Return the locally cached school logo without consulting Weave Cloud."""

        try:
            identity = node_identity_store.load()
        except NodeIdentityNotFoundError:
            return None

        state = await BrandingRepository.get_for_tenant(db, identity.tenant_id)
        if (
            state is None
            or state.logo_revision is None
            or not state.logo_storage_key
            or not state.logo_mime_type
            or not state.logo_sha256
        ):
            return None

        storage_key = state.logo_storage_key
        mime_type = state.logo_mime_type
        sha256 = state.logo_sha256
        revision = state.logo_revision
        await db.rollback()

        try:
            content = await self.logo_storage.read(storage_key)
        except (FileNotFoundError, OSError, BrandingLogoStorageError):
            return None

        return LocalBrandingLogo(
            content=content,
            mime_type=mime_type,
            sha256=sha256,
            revision=revision,
        )

    @staticmethod
    def _empty_logo_values() -> dict[str, object | None]:
        return {
            "logo_url": None,
            "logo_revision": None,
            "logo_storage_key": None,
            "logo_mime_type": None,
            "logo_size_bytes": None,
            "logo_sha256": None,
        }

    @staticmethod
    def _snapshot_logo_state(state: BrandingState | None) -> LogoCacheSnapshot | None:
        if state is None:
            return None
        return LogoCacheSnapshot(
            logo_url=state.logo_url,
            logo_revision=state.logo_revision,
            logo_storage_key=state.logo_storage_key,
            logo_mime_type=state.logo_mime_type,
            logo_size_bytes=state.logo_size_bytes,
            logo_sha256=state.logo_sha256,
        )

    @staticmethod
    def _logo_values_from_snapshot(
        snapshot: LogoCacheSnapshot,
    ) -> dict[str, object | None]:
        return {
            "logo_url": snapshot.logo_url,
            "logo_revision": snapshot.logo_revision,
            "logo_storage_key": snapshot.logo_storage_key,
            "logo_mime_type": snapshot.logo_mime_type,
            "logo_size_bytes": snapshot.logo_size_bytes,
            "logo_sha256": snapshot.logo_sha256,
        }

    async def _resolve_logo_values(
        self,
        *,
        projection: WeaveBrandingProjection,
        existing: LogoCacheSnapshot | None,
    ) -> dict[str, object | None]:
        has_url = bool(projection.logo_url)
        has_revision = projection.logo_revision is not None
        if has_url != has_revision:
            raise BrandingContractError(
                "Weave branding must provide logo_url and logo_revision together."
            )

        if not has_url:
            return self._empty_logo_values()

        if (
            existing is not None
            and existing.logo_revision == projection.logo_revision
            and existing.logo_storage_key
            and await self.logo_storage.exists(existing.logo_storage_key)
        ):
            return self._logo_values_from_snapshot(existing)

        if projection.logo_revision is None:
            raise BrandingContractError("Weave branding logo revision is missing.")

        try:
            cached = await self.logo_storage.cache_from_url(
                url=str(projection.logo_url),
                tenant_id=projection.tenant_id,
                revision=projection.logo_revision,
            )
        except BrandingLogoStorageError:
            logger.warning(
                "Unable to refresh the tenant logo; keeping the last valid local copy.",
                exc_info=True,
            )
            if (
                existing is not None
                and existing.logo_storage_key
                and await self.logo_storage.exists(existing.logo_storage_key)
            ):
                return self._logo_values_from_snapshot(existing)
            return self._empty_logo_values()

        return {
            "logo_url": str(projection.logo_url),
            "logo_revision": projection.logo_revision,
            "logo_storage_key": cached.storage_key,
            "logo_mime_type": cached.mime_type,
            "logo_size_bytes": cached.size_bytes,
            "logo_sha256": cached.sha256,
        }

    async def refresh_from_weave(self, db: AsyncSession) -> BrandingResponse:
        """Fetch Weave branding and atomically replace the effective local projection."""

        identity = node_identity_store.load()
        projection = await self.gateway.fetch_branding(
            server_credential=identity.server_credential,
        )
        if projection.tenant_id != identity.tenant_id:
            raise BrandingContractError(
                "Weave branding belongs to an unexpected tenant."
            )

        existing_row = await BrandingRepository.get_for_tenant(db, identity.tenant_id)
        existing = self._snapshot_logo_state(existing_row)
        old_storage_key = existing.logo_storage_key if existing is not None else None

        # Do not keep a PostgreSQL transaction open while downloading the
        # externally hosted logo. The filesystem/network work happens first;
        # only the final local projection replacement is transactional.
        await db.rollback()

        light_tokens = self.normalize_light_tokens(projection.light_tokens)
        logo_values = await self._resolve_logo_values(
            projection=projection,
            existing=existing,
        )
        new_storage_key = logo_values.get("logo_storage_key")

        values = {
            "tenant_id": projection.tenant_id,
            "school_name": projection.school_name,
            **logo_values,
            "is_enabled": projection.is_enabled,
            "is_default_theme": projection.is_default_theme,
            "theme_version": projection.theme_version,
            "token_schema_version": projection.token_schema_version,
            "light_tokens": light_tokens,
            "last_synced_at": datetime.now(UTC),
        }

        try:
            async with db.begin():
                state = await BrandingRepository.upsert(db, values=values)
        except Exception:
            if (
                isinstance(new_storage_key, str)
                and new_storage_key
                and new_storage_key != old_storage_key
            ):
                try:
                    await self.logo_storage.delete(new_storage_key)
                except (OSError, BrandingLogoStorageError):
                    logger.warning(
                        "Unable to remove uncommitted tenant logo cache.",
                        exc_info=True,
                    )
            raise

        if old_storage_key and old_storage_key != new_storage_key:
            try:
                await self.logo_storage.delete(old_storage_key)
            except (OSError, BrandingLogoStorageError):
                logger.warning(
                    "Unable to remove superseded tenant logo cache.",
                    exc_info=True,
                )

        return self._response_from_state(state)

    async def refresh_best_effort(self, db: AsyncSession) -> bool:
        """Refresh branding without allowing auxiliary branding failure to stop CBT work."""

        try:
            await self.refresh_from_weave(db)
            return True
        except NodeIdentityNotFoundError:
            await db.rollback()
            return False
        except Exception:
            await db.rollback()
            logger.warning(
                "Unable to refresh Weave tenant branding; keeping the last local theme.",
                exc_info=True,
            )
            return False


branding_service = BrandingService()
