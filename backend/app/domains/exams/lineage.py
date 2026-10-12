"""Shared SQL predicates for examination revision lineage."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.domains.exams.models import Exam


def latest_exam_revision_clause():
    """Return a correlated predicate that is true only for a lineage leaf.

    Revisions form a one-child chain through ``revision_of_exam_id``. Once an
    exam has a child revision, the parent remains queryable as historical
    evidence but must no longer participate in mutable or student-facing
    current-exam workflows.
    """

    child_exam = aliased(Exam)
    has_child_revision = (
        select(child_exam.id)
        .where(child_exam.revision_of_exam_id == Exam.id)
        .correlate(Exam)
        .exists()
    )
    return ~has_child_revision
