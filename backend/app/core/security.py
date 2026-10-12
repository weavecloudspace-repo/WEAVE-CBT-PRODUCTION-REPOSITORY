# ========================== #
# backend.app.core.security
# ========================== #

"""Low-level security primitives for the Weave CBT runtime."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import os
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from jose import ExpiredSignatureError, JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.settings import settings

# ========================== #
# LOCAL TOKEN CONSTANTS
# ========================== #

LOCAL_TOKEN_ISSUER = "weave-cbt"
LOCAL_TOKEN_AUDIENCE = "weave-cbt-local"
LOCAL_ACCESS_TOKEN_TYPE = "actor_access"
LOCAL_JWT_ALGORITHM = "HS256"

LOCAL_SIGNING_SECRET_FILENAME = "local_auth.secret"
LOCAL_SIGNING_SECRET_BYTES = 64
MIN_LOCAL_SIGNING_SECRET_LENGTH = 64

REFRESH_TOKEN_BYTES = 64
TOKEN_ID_BYTES = 24

WEAVE_CREDENTIAL_NONCE_BYTES = 12
WEAVE_CREDENTIAL_KEY_BYTES = 32
WEAVE_CREDENTIAL_HKDF_SALT = b"weave-cbt-auth-storage-v1"
WEAVE_CREDENTIAL_HKDF_INFO = b"weave/cbt/local-auth/weave-credentials"

# ========================== #
# CANDIDATE PIN CONSTANTS
# ========================== #

DEFAULT_CANDIDATE_PIN_LENGTH = 6
MIN_CANDIDATE_PIN_LENGTH = 6
MAX_CANDIDATE_PIN_LENGTH = 10

_RESERVED_ACCESS_TOKEN_CLAIMS = frozenset(
    {
        "iss",
        "aud",
        "sub",
        "iat",
        "nbf",
        "exp",
        "jti",
        "sid",
        "role",
        "installation_id",
        "token_type",
    }
)

_password_hash = PasswordHash.recommended()


# ========================== #
# EXCEPTIONS
# ========================== #


class SecurityError(Exception):
    """Base exception for local CBT security failures."""


class SecurityConfigurationError(SecurityError):
    """Raised when persistent local security state is missing or invalid."""


class InvalidLocalTokenError(SecurityError):
    """Raised when a local access token cannot be trusted."""


class ExpiredLocalTokenError(InvalidLocalTokenError):
    """Raised when a local access token has expired."""


class StoredCredentialHashError(SecurityError):
    """Raised when a stored candidate credential hash is invalid."""


class StoredSecretDecryptionError(SecurityError):
    """Raised when an encrypted local secret cannot be authenticated/decrypted."""


# ========================== #
# INTERNAL HELPERS
# ========================== #


def _local_signing_secret_path() -> Path:
    return settings.IDENTITY_STORAGE_PATH / LOCAL_SIGNING_SECRET_FILENAME


def _ensure_identity_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError as exc:
        raise SecurityConfigurationError(
            "Unable to initialize the CBT identity directory."
        ) from exc


def _restrict_secret_file_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        raise SecurityConfigurationError(
            "Unable to restrict local JWT signing-secret permissions."
        ) from exc


def _read_local_signing_secret(path: Path) -> str:
    secret = path.read_text(encoding="utf-8").strip()
    if not secret:
        raise SecurityConfigurationError("Local JWT signing-secret file is empty.")
    if len(secret) < MIN_LOCAL_SIGNING_SECRET_LENGTH:
        raise SecurityConfigurationError("Local JWT signing-secret file is invalid.")
    return secret


def _normalize_utc_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("datetime value must be timezone-aware.")
    return value.astimezone(UTC)


def _require_non_empty_string(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty.")
    return normalized


def _require_token_claim(payload: Mapping[str, Any], claim_name: str) -> str:
    value = payload.get(claim_name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidLocalTokenError(
            f"Local access token claim '{claim_name}' is invalid."
        )
    return value


def _is_valid_candidate_pin(pin: str) -> bool:
    return bool(
        isinstance(pin, str)
        and pin.isdigit()
        and MIN_CANDIDATE_PIN_LENGTH <= len(pin) <= MAX_CANDIDATE_PIN_LENGTH
    )


def _validate_candidate_pin(pin: str) -> None:
    if not _is_valid_candidate_pin(pin):
        raise ValueError(
            "Candidate PIN must contain only digits and be between "
            f"{MIN_CANDIDATE_PIN_LENGTH} and {MAX_CANDIDATE_PIN_LENGTH} "
            "characters long."
        )


# ========================== #
# PERSISTENT BACKEND SECRET
# ========================== #


@lru_cache(maxsize=1)
def get_local_signing_secret() -> str:
    """Load the persistent CBT backend signing secret without creating it."""

    secret_path = _local_signing_secret_path()
    try:
        return _read_local_signing_secret(secret_path)
    except FileNotFoundError as exc:
        raise SecurityConfigurationError(
            "Local JWT signing secret has not been initialized."
        ) from exc
    except OSError as exc:
        raise SecurityConfigurationError(
            "Unable to read the local JWT signing secret."
        ) from exc


def ensure_local_signing_secret() -> str:
    """Create the persistent CBT backend secret during pairing if necessary."""

    secret_path = _local_signing_secret_path()
    _ensure_identity_directory(secret_path.parent)

    try:
        existing_secret = _read_local_signing_secret(secret_path)
    except FileNotFoundError:
        existing_secret = None
    except OSError as exc:
        raise SecurityConfigurationError(
            "Unable to read the local JWT signing secret."
        ) from exc

    if existing_secret is not None:
        _restrict_secret_file_permissions(secret_path)
        return existing_secret

    secret = secrets.token_urlsafe(LOCAL_SIGNING_SECRET_BYTES)
    try:
        file_descriptor = os.open(
            secret_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        try:
            return _read_local_signing_secret(secret_path)
        except OSError as exc:
            raise SecurityConfigurationError(
                "Unable to read the local JWT signing secret."
            ) from exc
    except OSError as exc:
        raise SecurityConfigurationError(
            "Unable to create the local JWT signing secret."
        ) from exc

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as secret_file:
            secret_file.write(secret)
            secret_file.flush()
            os.fsync(secret_file.fileno())
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            secret_path.unlink()
        raise

    _restrict_secret_file_permissions(secret_path)
    get_local_signing_secret.cache_clear()
    _weave_credential_encryption_key.cache_clear()
    return secret


@lru_cache(maxsize=1)
def _weave_credential_encryption_key() -> bytes:
    """Derive an AES key from the same persistent CBT backend secret."""

    return HKDF(
        algorithm=hashes.SHA256(),
        length=WEAVE_CREDENTIAL_KEY_BYTES,
        salt=WEAVE_CREDENTIAL_HKDF_SALT,
        info=WEAVE_CREDENTIAL_HKDF_INFO,
    ).derive(get_local_signing_secret().encode("utf-8"))


def encrypt_local_secret(value: str, *, purpose: str) -> str:
    """Encrypt a recoverable secret using the persistent CBT backend secret."""

    plaintext = _require_non_empty_string(value, "value").encode("utf-8")
    associated_data = _require_non_empty_string(purpose, "purpose").encode("utf-8")
    nonce = secrets.token_bytes(WEAVE_CREDENTIAL_NONCE_BYTES)
    ciphertext = AESGCM(_weave_credential_encryption_key()).encrypt(
        nonce,
        plaintext,
        associated_data,
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_local_secret(value: str, *, purpose: str) -> str:
    """Authenticate and decrypt a secret encrypted by ``encrypt_local_secret``."""

    encoded = _require_non_empty_string(value, "value")
    associated_data = _require_non_empty_string(purpose, "purpose").encode("utf-8")
    try:
        payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
        nonce = payload[:WEAVE_CREDENTIAL_NONCE_BYTES]
        ciphertext = payload[WEAVE_CREDENTIAL_NONCE_BYTES:]
        if len(nonce) != WEAVE_CREDENTIAL_NONCE_BYTES or not ciphertext:
            raise ValueError("invalid encrypted payload")
        plaintext = AESGCM(_weave_credential_encryption_key()).decrypt(
            nonce,
            ciphertext,
            associated_data,
        )
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise StoredSecretDecryptionError(
            "Stored encrypted credential cannot be decrypted."
        ) from exc


# ========================== #
# GENERAL TOKEN PRIMITIVES
# ========================== #


def generate_token_id() -> str:
    return secrets.token_urlsafe(TOKEN_ID_BYTES)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    if not isinstance(token, str) or not token:
        raise ValueError("Refresh token cannot be empty.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_refresh_token(token: str, expected_hash: str) -> bool:
    if (
        not isinstance(token, str)
        or not token
        or not isinstance(expected_hash, str)
        or not expected_hash
    ):
        return False
    return secrets.compare_digest(hash_refresh_token(token), expected_hash)


# ========================== #
# LOCAL ACTOR ACCESS TOKENS
# ========================== #


def create_local_access_token(
    *,
    subject: str,
    session_id: str,
    role: str,
    installation_id: str,
    expires_at: datetime,
    additional_claims: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> str:
    """Create a local JWT whose expiry is supplied by the auth/session layer."""

    subject = _require_non_empty_string(subject, "subject")
    session_id = _require_non_empty_string(session_id, "session_id")
    role = _require_non_empty_string(role, "role")
    installation_id = _require_non_empty_string(installation_id, "installation_id")

    issued_at = _normalize_utc_datetime(now)
    normalized_expiry = _normalize_utc_datetime(expires_at)
    if normalized_expiry <= issued_at:
        raise ValueError("expires_at must be later than the access-token issue time.")

    payload: dict[str, Any] = {
        "iss": LOCAL_TOKEN_ISSUER,
        "aud": LOCAL_TOKEN_AUDIENCE,
        "sub": subject,
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int(normalized_expiry.timestamp()),
        "jti": generate_token_id(),
        "sid": session_id,
        "role": role,
        "installation_id": installation_id,
        "token_type": LOCAL_ACCESS_TOKEN_TYPE,
    }

    if additional_claims:
        protected_claims = _RESERVED_ACCESS_TOKEN_CLAIMS & set(additional_claims)
        if protected_claims:
            claim_names = ", ".join(sorted(protected_claims))
            raise ValueError(
                f"additional_claims cannot override protected JWT claims: {claim_names}"
            )
        payload.update(additional_claims)

    return jwt.encode(
        payload,
        get_local_signing_secret(),
        algorithm=LOCAL_JWT_ALGORITHM,
    )


def decode_local_access_token(token: str) -> dict[str, Any]:
    """Validate and decode a local actor access JWT."""

    if not isinstance(token, str) or not token.strip():
        raise InvalidLocalTokenError("Local access token is missing.")

    try:
        payload = jwt.decode(
            token,
            key=get_local_signing_secret(),
            algorithms=[LOCAL_JWT_ALGORITHM],
            audience=LOCAL_TOKEN_AUDIENCE,
            issuer=LOCAL_TOKEN_ISSUER,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_iss": True,
                "verify_aud": True,
                "verify_sub": True,
                "verify_jti": True,
                "require_exp": True,
                "require_iat": True,
                "require_nbf": True,
                "require_iss": True,
                "require_aud": True,
                "require_sub": True,
                "require_jti": True,
            },
        )
    except ExpiredSignatureError as exc:
        raise ExpiredLocalTokenError("Local access token has expired.") from exc
    except JWTError as exc:
        raise InvalidLocalTokenError("Local access token is invalid.") from exc

    _require_token_claim(payload, "sub")
    _require_token_claim(payload, "jti")
    _require_token_claim(payload, "sid")
    _require_token_claim(payload, "role")
    _require_token_claim(payload, "installation_id")
    token_type = _require_token_claim(payload, "token_type")
    if token_type != LOCAL_ACCESS_TOKEN_TYPE:
        raise InvalidLocalTokenError("Unexpected local token type.")
    return payload


# ========================== #
# CANDIDATE EXAM PIN
# ========================== #


def generate_candidate_pin(length: int = DEFAULT_CANDIDATE_PIN_LENGTH) -> str:
    if not (MIN_CANDIDATE_PIN_LENGTH <= length <= MAX_CANDIDATE_PIN_LENGTH):
        raise ValueError(
            "Candidate PIN length must be between "
            f"{MIN_CANDIDATE_PIN_LENGTH} and {MAX_CANDIDATE_PIN_LENGTH} digits."
        )
    value = secrets.randbelow(10**length)
    return f"{value:0{length}d}"


async def hash_candidate_pin(pin: str) -> str:
    _validate_candidate_pin(pin)
    return await asyncio.to_thread(_password_hash.hash, pin)


async def verify_candidate_pin(pin: str, hashed_pin: str) -> bool:
    if not _is_valid_candidate_pin(pin):
        return False
    if not isinstance(hashed_pin, str) or not hashed_pin:
        return False
    try:
        return await asyncio.to_thread(_password_hash.verify, pin, hashed_pin)
    except UnknownHashError as exc:
        raise StoredCredentialHashError(
            "Stored candidate PIN hash is invalid."
        ) from exc
