from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("WEAVE_API_BASE_URL", "https://weave.invalid")

from app.core import security


class StaffAuthSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        security._weave_credential_encryption_key.cache_clear()
        self.addCleanup(security._weave_credential_encryption_key.cache_clear)

    def test_weave_credential_encryption_round_trips_and_binds_purpose(self):
        root_secret = "s" * 96
        raw_token = "opaque-weave-refresh-token-value"

        with patch.object(
            security,
            "get_local_signing_secret",
            return_value=root_secret,
        ):
            encrypted = security.encrypt_local_secret(
                raw_token,
                purpose="auth:session:one:weave-refresh",
            )
            recovered = security.decrypt_local_secret(
                encrypted,
                purpose="auth:session:one:weave-refresh",
            )

            self.assertEqual(recovered, raw_token)
            self.assertNotEqual(encrypted, raw_token)
            self.assertNotIn(raw_token, encrypted)

            with self.assertRaises(security.StoredSecretDecryptionError):
                security.decrypt_local_secret(
                    encrypted,
                    purpose="auth:session:two:weave-refresh",
                )

    def test_local_access_token_uses_supplied_expiry(self):
        now = datetime.now(UTC).replace(microsecond=0)
        expires_at = now + timedelta(minutes=20)
        server_id = uuid4()
        session_id = uuid4()
        actor_id = uuid4()

        with patch.object(
            security,
            "get_local_signing_secret",
            return_value="k" * 96,
        ):
            token = security.create_local_access_token(
                subject=str(actor_id),
                session_id=str(session_id),
                role="teacher",
                installation_id=str(server_id),
                expires_at=expires_at,
                now=now,
            )
            payload = security.decode_local_access_token(token)

        self.assertEqual(payload["exp"], int(expires_at.timestamp()))
        self.assertEqual(payload["sid"], str(session_id))


if __name__ == "__main__":
    unittest.main()
