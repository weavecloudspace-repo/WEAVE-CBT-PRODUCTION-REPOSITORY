"""Local API schemas for synchronization status and reconciliation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SyncStatusResponse(BaseModel):
    scope: str
    schema_version: int
    cursor: int
    bootstrap_snapshot_id: UUID | None = None
    bootstrap_completed_at: datetime | None = None
    last_attempted_at: datetime | None = None
    last_successful_at: datetime | None = None
    last_error: str | None = None


class SyncReconcileResponse(SyncStatusResponse):
    previous_cursor: int
    changes_applied: int
    bootstrapped: bool
