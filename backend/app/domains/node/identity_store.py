# ================================#
# app.domains.node.identity_store
# ================================#
import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import ValidationError

from app.core.settings import settings
from app.domains.node.exceptions import (
    InstallationAlreadyPairedError,
    NodeIdentityCorruptError,
    NodeIdentityNotFoundError,
    NodeIdentityStorageError,
)
from app.domains.node.schemas import StoredNodeIdentity

IDENTITY_FILENAME = "installation.json"
PAIRING_LOCK_FILENAME = ".pairing.lock"

IDENTITY_DIRECTORY_MODE = 0o700
IDENTITY_FILE_MODE = 0o600
WINDOWS_LOCK_BYTES = 1


class NodeIdentityStore:
    """
    Filesystem-backed persistent store for this CBT installation's
    Weave machine identity

    The storage directory must live on the persistent Docker identity
    volume so the node idenenty survives container replacement,
    image upgrades , Docker restarts, and host restarts.


    This class does not perform pairing and does not communicate with Weave
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path = storage_path or settings.IDENTITY_STORAGE_PATH
        self.identity_path = self.storage_path / IDENTITY_FILENAME
        self.pairing_lock_path = self.storage_path / PAIRING_LOCK_FILENAME

    # ==========================#
    # STORAGE PREPARATION
    # ==========================#
    def ensure_storage_ready(self) -> None:
        """
        Ensure the persistent identity directory exists and is writeable

        On POSIX systems, the directory is restricted to the runtime user.

        A temporary probe file is created and removed to verify that
        this process can actually persist data before a one-time Weave
        pairing code is consumed
        """

        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)

            if not self.storage_path.is_dir():
                raise NodeIdentityStorageError(
                    "CBT identity storage path is not a directory"
                )

            self._restrict_directory_permissions(self.storage_path)

            self._verify_storage_writable()

        except NodeIdentityStorageError:
            raise

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Unable to initialize persistent CBT identity storage"
            ) from exc

    def _verify_storage_writable(self) -> None:
        """
        Verify that the identity directory is geninuely writeable.

        Checking permissions alone is insufficient because mounted
        volumes may still reject writes at runtime
        """

        probe_path = (
            self.storage_path / f".write-probe--{os.getpid()}--{secrets.token_hex(8)}"
        )

        file_descriptor: int | None = None

        try:
            file_descriptor = os.open(
                probe_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, IDENTITY_FILE_MODE
            )

            os.fsync(file_descriptor)

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Persistent CBT identity storage is not writeable"
            ) from exc

        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)

            try:
                probe_path.unlink()

            except FileNotFoundError:
                pass

            except OSError as exc:
                raise NodeIdentityStorageError(
                    "Unable to clean up the CBT identity storage probe"
                ) from exc

    # ==========================#
    # IDENTITY STATE
    # ==========================#

    def exists(self) -> bool:
        """
        Return whether persistent installation identity exists

        This does not validate the file contents
        """

        return self.identity_path.exists()

    def load(self) -> StoredNodeIdentity:
        """
        Load and validate the persisted CBT installation identity

        Missing identity represents an unpaired installation

        Existing but malformed identity is treated as corruption and
        must never silently fall back to an unpaired state
        """

        try:
            raw_content = self.identity_path.read_text(encoding="utf-8")

        except FileNotFoundError as exc:
            raise NodeIdentityNotFoundError(
                "CBT installaton has not been paired"
            ) from exc

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Unable to read persistent CBT installation identity"
            ) from exc

        try:
            payload = json.loads(raw_content)

        except json.JSONDecodeError as exc:
            raise NodeIdentityCorruptError(
                "Persistent CBT installation identity contains invalid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise NodeIdentityCorruptError(
                "Persistent CBT installation has an invalid structure"
            )

        try:
            identity = StoredNodeIdentity.model_validate(payload)

        except ValidationError as exc:
            raise NodeIdentityCorruptError(
                "Persistent CBT installation identity failed validation"
            ) from exc

        self._restrict_file_permissions(self.identity_path)

        return identity

    # ==========================#
    # INITIAL PERSISTENCE
    # ==========================#

    def update_hostname(self, *, server_id, hostname: str) -> StoredNodeIdentity:
        """Atomically update only the public hostname of an existing machine identity.

        The caller must hold pairing_lock to serialize identity changes across
        all local API processes. Machine credentials and owner never change.
        """
        from app.integrations.weave.certificates import verify_hostname

        valid_hostname = verify_hostname(hostname)
        identity = self.load()
        if identity.server_id != server_id:
            raise NodeIdentityCorruptError("Paired machine identity changed")
        if identity.hostname == valid_hostname:
            return identity
        updated = identity.model_copy(update={"hostname": valid_hostname})
        payload = updated.model_dump(mode="json", exclude={"server_credential"})
        payload["server_credential"] = updated.server_credential.get_secret_value()
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temporary_path = self.storage_path / f".hostname--{os.getpid()}--{secrets.token_hex(8)}.tmp"
        try:
            self._write_temporary_file(temporary_path, serialized)
            os.replace(temporary_path, self.identity_path)
            self._restrict_file_permissions(self.identity_path)
            self._sync_storage_directory()
        except OSError as exc:
            raise NodeIdentityStorageError("Unable to securely persist CBT hostname") from exc
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        return updated

    def save_initial(self, identity: StoredNodeIdentity) -> None:
        """
        Persist the initial Weave-issued node identity

        This operation is intentionally create-only

        Existing installation identity is never overwritten because doing so
        could silently replace one school's trusted machine identity with another

        The write is staged in a temporary file and then atomically linked
        into place
        """

        self.ensure_storage_ready()

        payload = identity.model_dump(mode="json", exclude={"server_credential"})

        # SecretStr deliberately masks values during normal serialization
        # Access the raw credential only at this persistent boundary
        payload["server_credential"] = identity.server_credential.get_secret_value()

        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

        temporary_path = (
            self.storage_path
            / f".installation--{os.getpid()}--{secrets.token_hex(8)}.tmp"
        )

        try:
            self._write_temporary_file(temporary_path, serialized)

            try:
                os.link(temporary_path, self.identity_path)

            except FileExistsError as exc:
                raise InstallationAlreadyPairedError(
                    "CBT installation is already paired"
                ) from exc

            self._restrict_file_permissions(self.identity_path)

            self._sync_storage_directory()

        except (InstallationAlreadyPairedError, NodeIdentityStorageError):
            raise

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Unable to persist CBT installation identity"
            ) from exc

        finally:
            try:
                temporary_path.unlink()

            except FileNotFoundError:
                pass

            except OSError:
                pass

    def _write_temporary_file(self, path: Path, content: str) -> None:
        """
        Write and fsync a private temporary identity file
        """

        file_descriptor: int | None = None

        try:
            file_descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                IDENTITY_FILE_MODE,
            )

            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
            ) as file:
                file_descriptor = None

                file.write(content)

                file.flush()
                os.fsync(file.fileno())

            self._restrict_file_permissions(path)

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Unable to stage CBT installation identity."
            ) from exc

        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)

    # ==========================#
    # PAIRING CONCURRENCT
    # ==========================#
    @asynccontextmanager
    async def pairing_lock(self):
        """
        Acquire an exclusive cross-process pairing lock

        Multiple FastAPI workers may serve the local CBT application

        Without this lock, two simultaneous pairing requests could both
        reach Weave before either has persisted installation.json

        The implementation uses the host platform's native file lock:
        `fcntl.flock` on POSIX and `msvcrt.locking` on Windows.
        """
        file_descriptor: int | None = None

        try:
            file_descriptor = await asyncio.to_thread(self._acquire_pairing_lock)

            yield

        finally:
            if file_descriptor is not None:
                await asyncio.to_thread(
                    self._release_pairing_lock,
                    file_descriptor,
                )

    @staticmethod
    def _is_windows() -> bool:
        return os.name == "nt"

    @staticmethod
    def _is_posix() -> bool:
        return os.name == "posix"

    def _acquire_pairing_lock(
        self,
    ) -> int:
        self.ensure_storage_ready()

        file_descriptor: int | None = None

        try:
            file_descriptor = os.open(
                self.pairing_lock_path,
                os.O_RDWR | os.O_CREAT,
                IDENTITY_FILE_MODE,
            )

            self._restrict_file_permissions(self.pairing_lock_path)

            if self._is_windows():
                self._acquire_windows_pairing_lock(file_descriptor)
            else:
                self._acquire_posix_pairing_lock(file_descriptor)

            return file_descriptor

        except OSError as exc:
            if file_descriptor is not None:
                os.close(file_descriptor)

            raise NodeIdentityStorageError(
                "Unable to acquire CBT installation pairing lock"
            ) from exc

    def _release_pairing_lock(
        self,
        file_descriptor: int,
    ) -> None:
        try:
            if self._is_windows():
                self._release_windows_pairing_lock(file_descriptor)
                return

            self._release_posix_pairing_lock(file_descriptor)

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Unable to release CBT installation pairing lock"
            ) from exc

        finally:
            os.close(file_descriptor)

    def _acquire_windows_pairing_lock(
        self,
        file_descriptor: int,
    ) -> None:
        import msvcrt

        self._prepare_windows_lock_file(file_descriptor)

        msvcrt.locking(
            file_descriptor,
            msvcrt.LK_LOCK,
            WINDOWS_LOCK_BYTES,
        )

    def _release_windows_pairing_lock(
        self,
        file_descriptor: int,
    ) -> None:
        import msvcrt

        os.lseek(file_descriptor, 0, os.SEEK_SET)
        msvcrt.locking(
            file_descriptor,
            msvcrt.LK_UNLCK,
            WINDOWS_LOCK_BYTES,
        )

    def _prepare_windows_lock_file(
        self,
        file_descriptor: int,
    ) -> None:
        os.lseek(file_descriptor, 0, os.SEEK_SET)

        if os.fstat(file_descriptor).st_size == 0:
            os.write(file_descriptor, b"0")
            os.fsync(file_descriptor)

        os.lseek(file_descriptor, 0, os.SEEK_SET)

    def _acquire_posix_pairing_lock(
        self,
        file_descriptor: int,
    ) -> None:
        import fcntl

        fcntl.flock(
            file_descriptor,
            fcntl.LOCK_EX,
        )

    def _release_posix_pairing_lock(
        self,
        file_descriptor: int,
    ) -> None:
        import fcntl

        fcntl.flock(
            file_descriptor,
            fcntl.LOCK_UN,
        )

    # ========================== #
    # PERMISSIONS / DURABILITY
    # ========================== #

    def _restrict_directory_permissions(
        self,
        path: Path,
    ) -> None:
        if not self._is_posix():
            return

        try:
            os.chmod(
                path,
                IDENTITY_DIRECTORY_MODE,
            )

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Unable to restrict CBT identity directory permissions."
            ) from exc

    @staticmethod
    def _restrict_file_permissions(
        path: Path,
    ) -> None:
        """
        Restrict a sensitive identity file to the runtime user on POSIX.
        """

        if os.name != "posix":
            return

        try:
            os.chmod(
                path,
                IDENTITY_FILE_MODE,
            )

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Unable to restrict CBT identity file permissions."
            ) from exc

    def _sync_storage_directory(self) -> None:
        """
        Flush directory metadata after creating installation.json.

        This improves durability across sudden host power loss.
        """

        if not self._is_posix():
            return

        directory_descriptor: int | None = None

        try:
            directory_descriptor = os.open(
                self.storage_path,
                os.O_RDONLY | os.O_DIRECTORY,
            )

            os.fsync(directory_descriptor)

        except OSError as exc:
            raise NodeIdentityStorageError(
                "Unable to synchronize CBT identity storage."
            ) from exc

        finally:
            if directory_descriptor is not None:
                os.close(directory_descriptor)


node_identity_store = NodeIdentityStore()
