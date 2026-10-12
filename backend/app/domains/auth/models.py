# =========================== #
#        auth/models.py       #
# =========================== #

"""Database models for local teacher and administrator authentication."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

WEAVE_ID_MAX_LENGTH = 128
ACTOR_ROLE_MAX_LENGTH = 64
ACTOR_EMAIL_MAX_LENGTH = 255
ACTOR_NAME_MAX_LENGTH = 255
REFRESH_TOKEN_HASH_LENGTH = 64
REVOCATION_REASON_MAX_LENGTH = 500
WEAVE_AUTH_STATE_MAX_LENGTH = 32

WEAVE_AUTH_STATE_LEGACY = "legacy"
WEAVE_AUTH_STATE_SYNCED = "synced"
WEAVE_AUTH_STATE_DEGRADED = "degraded"
WEAVE_AUTH_STATE_REFRESH_PENDING = "refresh_pending"
WEAVE_AUTH_STATE_REVOKED = "revoked"


class LocalActor(Base):
    """Local representation of Weave-authenticated staff."""

    __tablename__ = "local_actors"

    weave_actor_id: Mapped[str] = mapped_column(
        String(WEAVE_ID_MAX_LENGTH),
        nullable=False,
    )
    weave_membership_id: Mapped[str | None] = mapped_column(
        String(WEAVE_ID_MAX_LENGTH),
        nullable=True,
        unique=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(ACTOR_ROLE_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(ACTOR_EMAIL_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(
        String(ACTOR_NAME_MAX_LENGTH),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_weave_authenticated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_weave_revalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "weave_actor_id",
            "role",
            name="uq_local_actors_weave_actor_role",
        ),
        CheckConstraint(
            "char_length(trim(role)) > 0",
            name="ck_local_actors_role_not_blank",
        ),
        CheckConstraint(
            "char_length(trim(email)) > 0",
            name="ck_local_actors_email_not_blank",
        ),
        Index(
            "ix_local_actors_role_active",
            "role",
            "is_active",
        ),
    )


class LocalActorSession(Base):
    """One local CBT login session and its attached Weave authorization."""

    __tablename__ = "local_actor_sessions"

    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Absolute trust boundary. For all new sessions this is copied directly
    # from Weave's refresh_token_expires_at and never extended locally.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Weave actor credentials are opaque and must be recoverable for cloud
    # requests/rotation, so they are encrypted with the persistent CBT backend
    # secret rather than hashed. Nullable supports pre-migration legacy sessions
    # and secure clearing after revocation.
    weave_access_token_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    weave_access_token_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    weave_access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    weave_refresh_token_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    weave_refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    weave_auth_state: Mapped[str] = mapped_column(
        String(WEAVE_AUTH_STATE_MAX_LENGTH),
        nullable=False,
        default=WEAVE_AUTH_STATE_SYNCED,
        index=True,
    )
    weave_refresh_operation_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        index=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(REVOCATION_REASON_MAX_LENGTH),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="ck_local_actor_sessions_valid_expiry",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_local_actor_sessions_valid_revocation",
        ),
        CheckConstraint(
            "weave_auth_state IN ('legacy', 'synced', 'degraded', 'refresh_pending', 'revoked')",
            name="ck_local_actor_sessions_weave_auth_state",
        ),
        Index(
            "ix_local_actor_sessions_actor_expiry",
            "actor_id",
            "expires_at",
        ),
        Index(
            "ix_local_actor_sessions_actor_revoked",
            "actor_id",
            "revoked_at",
        ),
    )


class LocalRefreshToken(Base):
    """One rotating opaque browser-side local refresh token."""

    __tablename__ = "local_refresh_tokens"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actor_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(REFRESH_TOKEN_HASH_LENGTH),
        nullable=False,
        unique=True,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reuse_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replaced_by_token_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Response-recovery metadata for Browser -> CBT refresh ambiguity. The
    # replacement raw token is encrypted only so the same idempotent operation
    # can receive the exact replacement again after a lost HTTP response.
    refresh_operation_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        index=True,
    )
    replacement_token_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="ck_local_refresh_tokens_valid_expiry",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="ck_local_refresh_tokens_valid_consumed_at",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_local_refresh_tokens_valid_revoked_at",
        ),
        CheckConstraint(
            "reuse_detected_at IS NULL OR reuse_detected_at >= created_at",
            name="ck_local_refresh_tokens_valid_reuse_at",
        ),
        CheckConstraint(
            "replaced_by_token_id IS NULL OR replaced_by_token_id <> id",
            name="ck_local_refresh_tokens_not_self_replaced",
        ),
        Index(
            "ix_local_refresh_tokens_session_expiry",
            "session_id",
            "expires_at",
        ),
        Index(
            "ix_local_refresh_tokens_session_consumed",
            "session_id",
            "consumed_at",
        ),
    )
