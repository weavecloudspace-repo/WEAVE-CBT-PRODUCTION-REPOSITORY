import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

from pydantic import SecretStr

from app.domains.node.exceptions import (
    InstallationAlreadyPairedError,
)
from app.domains.node.identity_store import (
    IDENTITY_DIRECTORY_MODE,
    IDENTITY_FILE_MODE,
    WINDOWS_LOCK_BYTES,
    NodeIdentityStore,
)
from app.domains.node.schemas import StoredNodeIdentity


class NodeIdentityStoreSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = StoredNodeIdentity(
            server_id=uuid4(),
            server_name="Lab CBT Node",
            server_credential=SecretStr("super-secret-credential"),
            tenant_id=uuid4(),
            tenant_name="Weave Academy",
            paired_at=datetime(2026, 8, 14, 10, 30, tzinfo=UTC),
        )

    def test_save_initial_is_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = NodeIdentityStore(
                storage_path=Path(temp_dir),
            )

            store.save_initial(self.identity)

            with self.assertRaises(InstallationAlreadyPairedError):
                store.save_initial(self.identity)

            payload = json.loads(store.identity_path.read_text(encoding="utf-8"))

            self.assertEqual(
                payload["server_credential"],
                "super-secret-credential",
            )
            self.assertEqual(
                payload["server_name"],
                "Lab CBT Node",
            )


class NodeIdentityStorePlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(
            lambda: (
                Path(temp_dir).rmdir()
                if Path(temp_dir).exists() and not any(Path(temp_dir).iterdir())
                else None
            )
        )
        self.store = NodeIdentityStore(
            storage_path=Path(temp_dir),
        )

    def test_restrict_directory_permissions_is_posix_only(self) -> None:
        with (
            patch.object(self.store, "_is_posix", return_value=False),
            patch("app.domains.node.identity_store.os.chmod") as chmod_mock,
        ):
            self.store._restrict_directory_permissions(self.store.storage_path)

        chmod_mock.assert_not_called()

        with (
            patch.object(self.store, "_is_posix", return_value=True),
            patch("app.domains.node.identity_store.os.chmod") as chmod_mock,
        ):
            self.store._restrict_directory_permissions(self.store.storage_path)

        chmod_mock.assert_called_once_with(
            self.store.storage_path,
            IDENTITY_DIRECTORY_MODE,
        )

    def test_restrict_file_permissions_is_posix_only(self) -> None:
        with (
            patch("app.domains.node.identity_store.os.name", "nt"),
            patch("app.domains.node.identity_store.os.chmod") as chmod_mock,
        ):
            self.store._restrict_file_permissions(self.store.identity_path)

        chmod_mock.assert_not_called()

        with (
            patch("app.domains.node.identity_store.os.name", "posix"),
            patch("app.domains.node.identity_store.os.chmod") as chmod_mock,
        ):
            self.store._restrict_file_permissions(self.store.identity_path)

        chmod_mock.assert_called_once_with(
            self.store.identity_path,
            IDENTITY_FILE_MODE,
        )

    def test_sync_storage_directory_is_posix_only(self) -> None:
        with (
            patch.object(self.store, "_is_posix", return_value=False),
            patch("app.domains.node.identity_store.os.open") as open_mock,
        ):
            self.store._sync_storage_directory()

        open_mock.assert_not_called()

    def test_sync_storage_directory_uses_posix_directory_descriptor(self) -> None:
        with (
            patch.object(self.store, "_is_posix", return_value=True),
            patch(
                "app.domains.node.identity_store.os.open",
                return_value=11,
            ) as open_mock,
            patch("app.domains.node.identity_store.os.fsync") as fsync_mock,
            patch("app.domains.node.identity_store.os.close") as close_mock,
            patch(
                "app.domains.node.identity_store.os.O_DIRECTORY",
                65536,
                create=True,
            ),
        ):
            self.store._sync_storage_directory()

        open_mock.assert_called_once_with(
            self.store.storage_path,
            os.O_RDONLY | 65536,
        )
        fsync_mock.assert_called_once_with(11)
        close_mock.assert_called_once_with(11)

    def test_acquire_pairing_lock_dispatches_to_windows_helper(self) -> None:
        with (
            patch.object(self.store, "_is_windows", return_value=True),
            patch.object(self.store, "ensure_storage_ready") as ensure_mock,
            patch(
                "app.domains.node.identity_store.os.open",
                return_value=17,
            ) as open_mock,
            patch.object(self.store, "_restrict_file_permissions") as restrict_mock,
            patch.object(
                self.store,
                "_acquire_windows_pairing_lock",
            ) as windows_lock_mock,
            patch.object(
                self.store,
                "_acquire_posix_pairing_lock",
            ) as posix_lock_mock,
        ):
            file_descriptor = self.store._acquire_pairing_lock()

        self.assertEqual(file_descriptor, 17)
        ensure_mock.assert_called_once_with()
        open_mock.assert_called_once_with(
            self.store.pairing_lock_path,
            os.O_RDWR | os.O_CREAT,
            IDENTITY_FILE_MODE,
        )
        restrict_mock.assert_called_once_with(self.store.pairing_lock_path)
        windows_lock_mock.assert_called_once_with(17)
        posix_lock_mock.assert_not_called()

    def test_acquire_pairing_lock_dispatches_to_posix_helper(self) -> None:
        with (
            patch.object(self.store, "_is_windows", return_value=False),
            patch.object(self.store, "ensure_storage_ready") as ensure_mock,
            patch(
                "app.domains.node.identity_store.os.open",
                return_value=23,
            ) as open_mock,
            patch.object(self.store, "_restrict_file_permissions") as restrict_mock,
            patch.object(
                self.store,
                "_acquire_windows_pairing_lock",
            ) as windows_lock_mock,
            patch.object(
                self.store,
                "_acquire_posix_pairing_lock",
            ) as posix_lock_mock,
        ):
            file_descriptor = self.store._acquire_pairing_lock()

        self.assertEqual(file_descriptor, 23)
        ensure_mock.assert_called_once_with()
        open_mock.assert_called_once_with(
            self.store.pairing_lock_path,
            os.O_RDWR | os.O_CREAT,
            IDENTITY_FILE_MODE,
        )
        restrict_mock.assert_called_once_with(self.store.pairing_lock_path)
        posix_lock_mock.assert_called_once_with(23)
        windows_lock_mock.assert_not_called()

    def test_release_pairing_lock_unlocks_and_closes_on_windows(self) -> None:
        with (
            patch.object(self.store, "_is_windows", return_value=True),
            patch.object(
                self.store,
                "_release_windows_pairing_lock",
            ) as windows_release_mock,
            patch.object(
                self.store,
                "_release_posix_pairing_lock",
            ) as posix_release_mock,
            patch("app.domains.node.identity_store.os.close") as close_mock,
        ):
            self.store._release_pairing_lock(41)

        windows_release_mock.assert_called_once_with(41)
        posix_release_mock.assert_not_called()
        close_mock.assert_called_once_with(41)

    def test_release_pairing_lock_unlocks_and_closes_on_posix(self) -> None:
        with (
            patch.object(self.store, "_is_windows", return_value=False),
            patch.object(
                self.store,
                "_release_windows_pairing_lock",
            ) as windows_release_mock,
            patch.object(
                self.store,
                "_release_posix_pairing_lock",
            ) as posix_release_mock,
            patch("app.domains.node.identity_store.os.close") as close_mock,
        ):
            self.store._release_pairing_lock(43)

        posix_release_mock.assert_called_once_with(43)
        windows_release_mock.assert_not_called()
        close_mock.assert_called_once_with(43)

    def test_windows_pairing_lock_uses_msvcrt_locking(self) -> None:
        fake_msvcrt = SimpleNamespace(
            LK_LOCK=1,
            LK_UNLCK=2,
            locking=Mock(),
        )

        with (
            patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
            patch.object(self.store, "_prepare_windows_lock_file"),
            patch("app.domains.node.identity_store.os.lseek"),
        ):
            self.store._acquire_windows_pairing_lock(29)
            self.store._release_windows_pairing_lock(29)

        self.assertEqual(
            fake_msvcrt.locking.call_args_list[0].args,
            (29, fake_msvcrt.LK_LOCK, WINDOWS_LOCK_BYTES),
        )
        self.assertEqual(
            fake_msvcrt.locking.call_args_list[1].args,
            (29, fake_msvcrt.LK_UNLCK, WINDOWS_LOCK_BYTES),
        )

    def test_posix_pairing_lock_uses_fcntl_flock(self) -> None:
        fake_fcntl = SimpleNamespace(
            LOCK_EX=1,
            LOCK_UN=2,
            flock=Mock(),
        )

        with patch.dict(sys.modules, {"fcntl": fake_fcntl}):
            self.store._acquire_posix_pairing_lock(31)
            self.store._release_posix_pairing_lock(31)

        self.assertEqual(
            fake_fcntl.flock.call_args_list[0].args,
            (31, fake_fcntl.LOCK_EX),
        )
        self.assertEqual(
            fake_fcntl.flock.call_args_list[1].args,
            (31, fake_fcntl.LOCK_UN),
        )


class NodeIdentityStoreAsyncLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_pairing_lock_acquires_and_releases_in_worker_threads(self) -> None:
        store = NodeIdentityStore(
            storage_path=Path(tempfile.mkdtemp()),
        )

        with patch(
            "app.domains.node.identity_store.asyncio.to_thread",
            new=AsyncMock(side_effect=[71, None]),
        ) as to_thread_mock:
            async with store.pairing_lock():
                pass

        self.assertEqual(
            to_thread_mock.await_args_list[0].args,
            (store._acquire_pairing_lock,),
        )
        self.assertEqual(
            to_thread_mock.await_args_list[1].args,
            (store._release_pairing_lock, 71),
        )

    async def test_pairing_lock_releases_when_body_raises(self) -> None:
        store = NodeIdentityStore(
            storage_path=Path(tempfile.mkdtemp()),
        )

        with (
            patch(
                "app.domains.node.identity_store.asyncio.to_thread",
                new=AsyncMock(side_effect=[73, None]),
            ) as to_thread_mock,
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            async with store.pairing_lock():
                raise RuntimeError("boom")

        self.assertEqual(
            to_thread_mock.await_args_list[1].args,
            (store._release_pairing_lock, 73),
        )


if __name__ == "__main__":
    unittest.main()
