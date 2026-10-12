# =========================== #
#       audit/models.py       #
# =========================== #

"""Database models for permanent CBT audit history."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy import (
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

AUDIT_ACTION_MAX_LENGTH = 128
AUDIT_ENTITY_TYPE_MAX_LENGTH = 64
AUDIT_ENTITY_LABEL_MAX_LENGTH = 255
AUDIT_ACTOR_TYPE_MAX_LENGTH = 64
AUDIT_ACTOR_ROLE_MAX_LENGTH = 64
AUDIT_ACTOR_NAME_MAX_LENGTH = 255
AUDIT_REQUEST_ID_MAX_LENGTH = 128
AUDIT_IP_ADDRESS_MAX_LENGTH = 45


class AuditActorType(StrEnum):
    """Types of actors capable of producing audit events."""

    LOCAL_ACTOR = "local_actor"
    CANDIDATE = "candidate"
    SYSTEM = "system"


class AuditOutcome(StrEnum):
    """Outcome of an audited operation."""

    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


class AuditEvent(Base):
    """
    Permanent record of an important action performed within the CBT system.

    Audit events intentionally avoid foreign-key relationships to the actor
    or affected entity. This allows audit history to remain readable even if
    the original record is later deactivated, archived, or removed.

    Audit rows should be append-only. Application services must never edit or
    delete existing audit events during normal operation.
    """

    __tablename__ = "audit_events"

    actor_type: Mapped[AuditActorType] = mapped_column(
        SQLEnum(
            AuditActorType,
            name="audit_actor_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )

    actor_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        index=True,
    )

    actor_name: Mapped[str | None] = mapped_column(
        String(AUDIT_ACTOR_NAME_MAX_LENGTH),
        nullable=True,
    )

    actor_role: Mapped[str | None] = mapped_column(
        String(AUDIT_ACTOR_ROLE_MAX_LENGTH),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(
        String(AUDIT_ACTION_MAX_LENGTH),
        nullable=False,
        index=True,
    )

    outcome: Mapped[AuditOutcome] = mapped_column(
        SQLEnum(
            AuditOutcome,
            name="audit_outcome",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=AuditOutcome.SUCCESS,
        server_default=AuditOutcome.SUCCESS.value,
        index=True,
    )

    entity_type: Mapped[str | None] = mapped_column(
        String(AUDIT_ENTITY_TYPE_MAX_LENGTH),
        nullable=True,
        index=True,
    )

    entity_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        index=True,
    )

    entity_label: Mapped[str | None] = mapped_column(
        String(AUDIT_ENTITY_LABEL_MAX_LENGTH),
        nullable=True,
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        String(AUDIT_REQUEST_ID_MAX_LENGTH),
        nullable=True,
        index=True,
    )

    client_ip: Mapped[str | None] = mapped_column(
        String(AUDIT_IP_ADDRESS_MAX_LENGTH),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_audit_events_actor_created",
            "actor_type",
            "actor_id",
            "created_at",
        ),
        Index(
            "ix_audit_events_entity_created",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index(
            "ix_audit_events_action_created",
            "action",
            "created_at",
        ),
        Index(
            "ix_audit_events_outcome_created",
            "outcome",
            "created_at",
        ),
    )
