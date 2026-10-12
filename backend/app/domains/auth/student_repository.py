"""Persistence helpers for opaque student examination sessions."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.student_models import StudentExamSession

_ADVISORY_LOCK_MASK = (1 << 64) - 1
_ADVISORY_LOCK_SIGN_BIT = 1 << 63
_ADVISORY_LOCK_MODULUS = 1 << 64


def _student_session_lock_key(student_id: UUID) -> int:
    """Map a student UUID to PostgreSQL's signed 64-bit advisory-lock space."""

    # UUIDs are 128-bit while pg_advisory_xact_lock(bigint) accepts 64 bits.
    # Fold both UUID halves together so the lock key depends on the full UUID.
    folded = ((student_id.int >> 64) ^ student_id.int) & _ADVISORY_LOCK_MASK
    if folded >= _ADVISORY_LOCK_SIGN_BIT:
        folded -= _ADVISORY_LOCK_MODULUS
    return folded


class StudentAuthRepository:
    @staticmethod
    async def add_session(
        db: AsyncSession, session: StudentExamSession
    ) -> StudentExamSession:
        db.add(session)
        await db.flush()
        return session

    @staticmethod
    async def save_session(
        db: AsyncSession, session: StudentExamSession
    ) -> StudentExamSession:
        db.add(session)
        await db.flush()
        return session

    @staticmethod
    async def get_session_by_hash(
        db: AsyncSession,
        token_hash: str,
        *,
        lock: bool = False,
    ) -> StudentExamSession | None:
        query = select(StudentExamSession).where(
            StudentExamSession.token_hash == token_hash
        )
        if lock:
            query = query.with_for_update(of=StudentExamSession)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_unrevoked_sessions_for_candidate(
        db: AsyncSession,
        candidate_id: UUID,
        *,
        lock: bool = False,
    ) -> list[StudentExamSession]:
        query = select(StudentExamSession).where(
            StudentExamSession.candidate_id == candidate_id,
            StudentExamSession.revoked_at.is_(None),
        )
        if lock:
            query = query.with_for_update(of=StudentExamSession)
        result = await db.execute(query.order_by(StudentExamSession.created_at.asc()))
        return list(result.scalars().all())

    @staticmethod
    async def list_unrevoked_sessions_for_exam(
        db: AsyncSession,
        exam_id: UUID,
        *,
        lock: bool = False,
    ) -> list[StudentExamSession]:
        query = select(StudentExamSession).where(
            StudentExamSession.exam_id == exam_id,
            StudentExamSession.revoked_at.is_(None),
        )
        if lock:
            query = query.with_for_update(of=StudentExamSession)
        result = await db.execute(query.order_by(StudentExamSession.created_at.asc()))
        return list(result.scalars().all())

    @staticmethod
    async def list_unrevoked_sessions_for_student(
        db: AsyncSession,
        student_id: UUID,
        *,
        lock: bool = False,
    ) -> list[StudentExamSession]:
        if lock:
            # Row locks alone cannot serialize two first-time/waiting-room logins
            # when no StudentExamSession row exists yet. A transaction-scoped
            # advisory lock gives every API replica the same per-student mutex.
            # It is released automatically on commit/rollback.
            await db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _student_session_lock_key(student_id)},
            )

        query = select(StudentExamSession).where(
            StudentExamSession.student_id == student_id,
            StudentExamSession.revoked_at.is_(None),
        )
        if lock:
            query = query.with_for_update(of=StudentExamSession)
        result = await db.execute(query.order_by(StudentExamSession.created_at.asc()))
        return list(result.scalars().all())

    @staticmethod
    async def save_sessions(
        db: AsyncSession,
        sessions: Sequence[StudentExamSession],
    ) -> list[StudentExamSession]:
        rows = list(sessions)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows
