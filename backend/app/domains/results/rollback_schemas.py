"""CBT result rollback request and status contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LocalRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=5, max_length=1024)


class CloudRollbackItem(BaseModel):
    student_id: UUID
    status: Literal["pending", "completed", "rejected"]
    error_code: str | None = None
    error_detail: str | None = None


class CloudRollbackResponse(BaseModel):
    operation_id: UUID
    source_batch_id: UUID
    status: Literal[
        "pending", "processing", "completed", "partially_completed", "rejected"
    ]
    target_count: int
    completed_count: int
    rejected_count: int
    completed_at: datetime | None = None
    items: list[CloudRollbackItem] = Field(default_factory=list)


class LocalRollbackResponse(BaseModel):
    operation_id: UUID
    source_batch_id: UUID
    status: str
    results: list[UUID] = Field(default_factory=list)
    completed_count: int = 0
    rejected_count: int = 0
    error: str | None = None
