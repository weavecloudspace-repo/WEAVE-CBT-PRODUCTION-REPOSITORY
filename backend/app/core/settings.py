# ========================== #
# backend.app.core.settings
# ========================== #

"""Runtime configuration for the Weave CBT application.

Architecture rules:

- PostgreSQL is the durable source of truth for local examination state.
- Redis is used only for caching, coordination, rate limiting, and workers.
- Weave remains authoritative for staff identity and cloud actor authorization.
- Local staff sessions mirror Weave's hard authorization deadline while keeping
  local examination workflows available during internet outages.
- Active examinations must not depend on continuous Weave connectivity.
- Installation identity and credentials are persistent runtime state and are
  not configured through environment variables.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported application runtime environments."""

    DEVELOPMENT = "dev"
    STAGING = "stg"
    PRODUCTION = "prod"


class Settings(BaseSettings):
    """Application runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
        frozen=True,
    )

    # ========================== #
    # APPLICATION
    # ========================== #

    APP_NAME: str = "Weave CBT"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = Environment.PRODUCTION
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=8000, ge=1, le=65535)
    LOG_LEVEL: str = "INFO"

    # ========================== #
    # POSTGRESQL
    # ========================== #

    DATABASE_URL: str = Field(
        ...,
        min_length=1,
        description="Required PostgreSQL connection URL for the local CBT database.",
    )
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1)
    DATABASE_MAX_OVERFLOW: int = Field(default=5, ge=0)
    DATABASE_POOL_TIMEOUT_SECONDS: int = Field(default=10, ge=1)
    DATABASE_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60)

    # ========================== #
    # REDIS
    # ========================== #

    REDIS_URL: str = Field(
        ...,
        min_length=1,
        description=(
            "Redis connection URL used for cache, coordination, rate limiting, "
            "and other temporary state."
        ),
    )
    REDIS_CONNECT_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)
    REDIS_SOCKET_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)
    REDIS_HEALTH_CHECK_INTERVAL_SECONDS: int = Field(default=30, ge=1)
    REDIS_MAX_CONNECTIONS: int = Field(default=20, ge=1)

    # ========================== #
    # PERSISTENT CBT IDENTITY
    # ========================== #

    # Back this directory with persistent Docker storage. It contains the
    # installation identity, Weave-issued server credential, and the persistent
    # CBT backend secret used for local JWT signing and auth credential encryption.
    IDENTITY_STORAGE_PATH: Path = Path("/var/lib/weave-cbt/identity")

    # ========================== #
    # LOCAL MEDIA STORAGE
    # ========================== #

    MEDIA_STORAGE_PATH: Path = Path("/var/lib/weave-cbt/media")
    MEDIA_MAX_IMAGE_SIZE_BYTES: int = Field(default=5 * 1024 * 1024, ge=1)

    # ========================== #
    # TENANT BRANDING CACHE
    # ========================== #

    BRANDING_LOGO_STORAGE_PATH: Path = Path("/var/lib/weave-cbt/branding")
    BRANDING_LOGO_MAX_SIZE_BYTES: int = Field(default=2 * 1024 * 1024, ge=1)

    # ========================== #
    # WEAVE CLOUD INTEGRATION
    # ========================== #

    WEAVE_API_BASE_URL: AnyHttpUrl
    WEAVE_REQUEST_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    WEAVE_CONNECT_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)

    # ========================== #
    # HTTP / FRONTEND
    # ========================== #

    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:3002",
            "http://127.0.0.1:3002",
        ]
    )

    # ========================== #
    # SENTRY
    # ========================== #

    SENTRY_BACKEND_DSN_URL: str | None = None

    # ========================== #
    # VALIDATION
    # ========================== #

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        value = value.strip()
        prefix_mappings = {
            "postgresql://": "postgresql+asyncpg://",
            "postgres://": "postgresql+asyncpg://",
            "postgresql+psycopg://": "postgresql+asyncpg://",
            "postgresql+psycopg2://": "postgresql+asyncpg://",
        }
        for source_prefix, async_prefix in prefix_mappings.items():
            if value.startswith(source_prefix):
                return value.replace(source_prefix, async_prefix, 1)
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use PostgreSQL with the asyncpg driver."
            )
        return value

    @field_validator("REDIS_URL")
    @classmethod
    def validate_redis_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("Redis URLs must use either 'redis://' or 'rediss://'.")
        return value

    @field_validator("LOG_LEVEL")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        valid_levels = {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }
        if normalized not in valid_levels:
            raise ValueError(
                f"LOG_LEVEL must be one of: {', '.join(sorted(valid_levels))}"
            )
        return normalized

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for origin in value:
            origin = origin.strip().rstrip("/")
            if not origin:
                continue
            if origin == "*":
                normalized.append(origin)
                continue
            if not origin.startswith(("http://", "https://")):
                raise ValueError(
                    "CORS_ORIGINS entries must use 'http://' or 'https://'."
                )
            normalized.append(origin)
        return normalized

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        if self.ENVIRONMENT == Environment.PRODUCTION and self.DEBUG:
            raise ValueError("DEBUG must be disabled in production.")
        if self.ENVIRONMENT == Environment.PRODUCTION and "*" in self.CORS_ORIGINS:
            raise ValueError("Wildcard CORS origins are not allowed in production.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated, process-wide frozen settings instance."""

    return Settings()


settings = get_settings()
