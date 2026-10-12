"""Schemas for examination collection reads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domains.exams.schemas import ExamResponse


class ExamListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    offset: int
    limit: int
    total: int
    exams: list[ExamResponse]
