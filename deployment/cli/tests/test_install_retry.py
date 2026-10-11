"""Safe recovery of partially completed WEAVE CBT first installations.

These tests only use temporary filesystem paths and never invoke Docker.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weave_cli.commands import install


IMAGE_OLD = "ghcr.io/weavecloudspace-repo/weave-cbt-production-repository@sha256:" + "a" * 64
IMAGE_NEW = "ghcr.io/weavecloudspace-repo/weave-cbt-production-repository@sha256:" + "b" * 64


def release(*, channel: str = "staging", image: str = IMAGE_NEW, api: str = "https://weave.example.test") -> dict:
    return {"channel": channel, "image": image, "api": api}


def saved_configuration(*, image: str = IMAGE_OLD, channel: str = "stg", api: str = "https://weave.example.test") -> bytes:
    secret = "a-strong-preserved-postgres-secret-123"
    return (
        f"ENVIRONMENT={channel}\n"
        f"WEAVE_API_BASE_URL={api}\n"
        f"WEAVE_IMAGE={image}\n"
        f"POSTGRES_DB=weave_cbt\n"
        f"POSTGRES_USER=weave\n"
        f"POSTGRES_PASSWORD={secret}\n"
        f"DATABASE_URL=postgresql+asyncpg://weave:{secret}@postgres:5432/weave_cbt\n"
        "REDIS_URL=redis://redis:6379/0\n"
        "CUSTOM_SECRET=must-remain-untouched\n"
    ).encode("utf-8")


class InstallationRetryEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.path = self.data / "runtime.env"

    def test_same_channel_different_pinned_image_reuses_credentials_without_modification(self):
        original = saved_configuration()
        self.path.write_bytes(original)
        with patch.object(install, "warning") as notice:
            selected = install._prepare_environment(self.data, release())
        self.assertEqual(selected, self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(install._read_environment(selected)["WEAVE_IMAGE"], IMAGE_OLD)
        self.assertIn("weave update", notice.call_args.args[0])

    def test_matching_image_is_idempotent_and_does_not_warn(self):
        original = saved_configuration(image=IMAGE_NEW)
        self.path.write_bytes(original)
        with patch.object(install, "warning") as notice:
            self.assertEqual(install._prepare_environment(self.data, release()), self.path)
        self.assertEqual(self.path.read_bytes(), original)
        notice.assert_not_called()

    def test_channel_mismatch_does_not_modify_credentials(self):
        original = saved_configuration(channel="prod")
        self.path.write_bytes(original)
        with self.assertRaisesRegex(install.InstallError, "release channel"):
            install._prepare_environment(self.data, release())
        self.assertEqual(self.path.read_bytes(), original)

    def test_api_mismatch_does_not_modify_credentials(self):
        original = saved_configuration(api="https://other.example.test")
        self.path.write_bytes(original)
        with self.assertRaisesRegex(install.InstallError, "WEAVE API"):
            install._prepare_environment(self.data, release())
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_or_missing_credentials_still_fail(self):
        original = saved_configuration().replace(
            b"POSTGRES_PASSWORD=a-strong-preserved-postgres-secret-123",
            b"POSTGRES_PASSWORD=example",
        )
        self.path.write_bytes(original)
        with self.assertRaises(install.InstallError):
            install._prepare_environment(self.data, release())
        self.assertEqual(self.path.read_bytes(), original)

    def test_new_environment_generates_pinned_image_and_unique_secrets(self):
        selected = install._prepare_environment(self.data, release())
        parsed = install._read_environment(selected)
        self.assertEqual(parsed["WEAVE_IMAGE"], IMAGE_NEW)
        self.assertEqual(parsed["ENVIRONMENT"], "stg")
        self.assertEqual(parsed["WEAVE_API_BASE_URL"], "https://weave.example.test")
        self.assertGreaterEqual(len(parsed["POSTGRES_PASSWORD"]), 16)

    def test_source_checkout_without_manifest_is_still_rejected(self):
        with self.assertRaisesRegex(install.InstallError, "release manifest"):
            install._prepare_environment(self.data, None)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
