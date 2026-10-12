from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import InvalidRequestError

from app.domains.auth.dependencies import get_current_local_context
from app.domains.auth.repository import AuthRepository
from app.domains.auth.student_dependencies import get_current_student_session
from app.domains.auth.student_lifecycle_service import (
    StudentAuthService,
    StudentSessionContext,
)


class _TransactionContext:
    def __init__(self, db: _TransactionAwareDb) -> None:
        self.db = db

    async def __aenter__(self):
        if self.db.active_transaction:
            raise InvalidRequestError("A transaction is already begun on this Session.")
        self.db.active_transaction = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.db.active_transaction = False
        return False


class _TransactionAwareDb:
    def __init__(self) -> None:
        self.active_transaction = False
        self.begin_calls = 0
        self.commit_calls = 0

    def begin(self) -> _TransactionContext:
        self.begin_calls += 1
        return _TransactionContext(self)

    def in_transaction(self) -> bool:
        return self.active_transaction

    async def commit(self) -> None:
        self.commit_calls += 1
        self.active_transaction = False


class LocalAuthDependencyTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorization_transaction_is_closed_before_route_service_runs(self):
        db = _TransactionAwareDb()
        session_id = uuid4()
        actor_id = uuid4()
        server_id = uuid4()
        weave_actor_id = uuid4()
        session = SimpleNamespace(
            id=session_id,
            actor_id=actor_id,
            revoked_at=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        actor = SimpleNamespace(
            id=actor_id,
            weave_actor_id=str(weave_actor_id),
            role="admin",
            is_active=True,
        )
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="local-access",
        )
        payload = {
            "sid": str(session_id),
            "sub": str(weave_actor_id),
            "role": "admin",
            "installation_id": str(server_id),
        }

        with (
            patch(
                "app.domains.auth.dependencies.decode_local_access_token",
                return_value=payload,
            ),
            patch(
                "app.domains.auth.dependencies.node_identity_store.load",
                return_value=SimpleNamespace(server_id=server_id),
            ),
            patch.object(
                AuthRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=session),
            ),
            patch.object(
                AuthRepository,
                "get_actor_by_id",
                new=AsyncMock(return_value=actor),
            ),
        ):
            context = await get_current_local_context(db, credentials)

        self.assertIs(context.session, session)
        self.assertIs(context.actor, actor)
        self.assertFalse(db.active_transaction)
        self.assertEqual(db.begin_calls, 1)

        # Regression guard for cloud-backed routes: the service must be able to
        # immediately open its own top-level transaction on the same request DB.
        async with db.begin():
            self.assertTrue(db.active_transaction)

        self.assertFalse(db.active_transaction)
        self.assertEqual(db.begin_calls, 2)

    async def test_student_dependency_closes_implicit_read_transaction(self):
        db = _TransactionAwareDb()
        context = StudentSessionContext(
            session_id=uuid4(),
            student_id=uuid4(),
            candidate_id=uuid4(),
            exam_id=uuid4(),
            makeup_authorization_id=None,
        )

        async def resolve_session(_db, *, raw_token: str):
            self.assertEqual(raw_token, "student-session-token")
            # Model SQLAlchemy autobegin caused by the dependency's first SELECT.
            _db.active_transaction = True
            return context

        with patch.object(
            StudentAuthService,
            "resolve_session",
            new=AsyncMock(side_effect=resolve_session),
        ):
            resolved = await get_current_student_session(
                db,
                raw_token="student-session-token",
            )

        self.assertIs(resolved, context)
        self.assertFalse(db.active_transaction)
        self.assertEqual(db.commit_calls, 1)

        # A protected student route may later adopt an explicit transaction;
        # dependency resolution must never prevent that top-level begin().
        async with db.begin():
            self.assertTrue(db.active_transaction)

        self.assertFalse(db.active_transaction)


if __name__ == "__main__":
    unittest.main()
