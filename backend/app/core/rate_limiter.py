# ========================== #
# backend.app.core.rate_limiter
# ========================== #

"""
Generic Redis-backed rate-limiting infrastructure for Weave CBT.

Responsibilities:

- define reusable rate-limit policies;
- construct privacy-safe Redis rate-limit keys;
- atomically consume rate-limit capacity;
- report remaining capacity and retry timing;
- reset rate-limit state when explicitly required.

This module does NOT:

- know about teachers, admins, candidates, or examinations;
- authenticate users;
- verify passwords or candidate PINs;
- decide which endpoints should be rate limited;
- return FastAPI HTTP responses;
- contain domain-specific authorization logic.

Domain/router dependency layers decide:

- which identifier should be limited;
- which policy applies;
- how an exceeded limit should be represented to the client.

Redis is temporary infrastructure. Rate-limit state is intentionally
non-durable and must never contain examination-critical data.
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

# ========================== #
# CONSTANTS
# ========================== #

RATE_LIMIT_KEY_PREFIX = "weave-cbt:ratelimit"

MIN_RATE_LIMIT = 1
MIN_WINDOW_SECONDS = 1

MAX_SCOPE_LENGTH = 64


# ========================== #
# LUA SCRIPT
# ========================== #

# Atomic fixed-window rate limiter.
#
# KEYS[1]
#   Redis rate-limit key.
#
# ARGV[1]
#   Maximum number of permitted operations.
#
# ARGV[2]
#   Window duration in seconds.
#
# Returns:
#
# [
#   allowed,
#   current_count,
#   ttl_seconds
# ]
#
# allowed:
#   1 = request consumed capacity successfully
#   0 = limit already reached
#
# The counter is intentionally capped at the policy limit rather
# than increasing indefinitely after the caller is already blocked.

_RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])

local current = tonumber(redis.call("GET", key) or "0")

if current >= limit then
    local ttl = redis.call("TTL", key)

    if ttl < 0 then
        redis.call("EXPIRE", key, window_seconds)
        ttl = window_seconds
    end

    return {0, current, ttl}
end

current = redis.call("INCR", key)

if current == 1 then
    redis.call("EXPIRE", key, window_seconds)
end

local ttl = redis.call("TTL", key)

if ttl < 0 then
    redis.call("EXPIRE", key, window_seconds)
    ttl = window_seconds
end

return {1, current, ttl}
"""


# ========================== #
# EXCEPTIONS
# ========================== #


class RateLimiterError(Exception):
    """Base exception for rate-limiter infrastructure failures."""


class RateLimiterConfigurationError(RateLimiterError):
    """Raised when a rate-limit policy or scope is invalid."""


class RateLimiterBackendUnavailableError(RateLimiterError):
    """Raised when Redis cannot service a rate-limit operation."""


class RateLimiterResponseError(RateLimiterError):
    """Raised when Redis returns an unexpected limiter response."""


# ========================== #
# DATA STRUCTURES
# ========================== #


@dataclass(
    frozen=True,
    slots=True,
)
class RateLimitPolicy:
    """
    Reusable rate-limit configuration.

    Example:

        RateLimitPolicy(
            limit=5,
            window_seconds=60,
        )

    means:

        at most 5 operations
        during a 60-second window.
    """

    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit < MIN_RATE_LIMIT:
            raise RateLimiterConfigurationError(
                f"Rate-limit policy limit must be at least {MIN_RATE_LIMIT}."
            )

        if self.window_seconds < MIN_WINDOW_SECONDS:
            raise RateLimiterConfigurationError(
                "Rate-limit policy window must be at least "
                f"{MIN_WINDOW_SECONDS} second."
            )


@dataclass(
    frozen=True,
    slots=True,
)
class RateLimitDecision:
    """
    Result of consuming rate-limit capacity.

    allowed:
        Whether the operation may continue.

    limit:
        Maximum permitted operations in the window.

    remaining:
        Number of additional operations currently available.

    retry_after_seconds:
        Number of seconds until the current counter expires.

    current_count:
        Number of consumed operations in the current window.
    """

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    current_count: int


# ========================== #
# INTERNAL VALIDATION
# ========================== #


def _validate_scope(
    scope: str,
) -> str:
    """
    Validate and normalize a rate-limit scope.

    Scopes should describe functionality rather than user input.

    Examples:

    - candidate-login
    - actor-login
    - pairing
    - token-refresh
    """

    if not isinstance(scope, str):
        raise RateLimiterConfigurationError("Rate-limit scope must be a string.")

    normalized = scope.strip().lower()

    if not normalized:
        raise RateLimiterConfigurationError("Rate-limit scope cannot be empty.")

    if len(normalized) > MAX_SCOPE_LENGTH:
        raise RateLimiterConfigurationError("Rate-limit scope is too long.")

    if not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]*",
        normalized,
    ):
        raise RateLimiterConfigurationError(
            "Rate-limit scope may contain only lowercase letters, "
            "numbers, '.', '_' and '-'."
        )

    return normalized


def _validate_identifier(
    identifier: str,
) -> str:
    """
    Validate a logical rate-limit identifier.

    Identifiers may contain sensitive values such as:

    - admission numbers;
    - email addresses;
    - installation identifiers.

    The raw value is never placed directly into the Redis key.
    """

    if not isinstance(identifier, str):
        raise RateLimiterConfigurationError("Rate-limit identifier must be a string.")

    normalized = identifier.strip()

    if not normalized:
        raise RateLimiterConfigurationError("Rate-limit identifier cannot be empty.")

    return normalized


# ========================== #
# INTERNAL KEY HELPERS
# ========================== #


def _hash_rate_limit_identifier(
    identifier: str,
) -> str:
    """
    Return a deterministic SHA-256 fingerprint for an identifier.

    This avoids exposing raw admission numbers, email addresses,
    or similar identifiers inside Redis key names.
    """

    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()


def _build_rate_limit_key(
    *,
    scope: str,
    identifier: str,
) -> str:
    """
    Construct the Redis key used by the rate limiter.
    """

    normalized_scope = _validate_scope(scope)

    normalized_identifier = _validate_identifier(identifier)

    identifier_hash = _hash_rate_limit_identifier(normalized_identifier)

    return f"{RATE_LIMIT_KEY_PREFIX}:{normalized_scope}:{identifier_hash}"


# ========================== #
# INTERNAL RESPONSE HANDLING
# ========================== #


def _parse_rate_limit_response(
    response: Any,
    *,
    policy: RateLimitPolicy,
) -> RateLimitDecision:
    """
    Convert the Redis Lua response into a typed decision.
    """

    if not isinstance(response, (list, tuple)) or len(response) != 3:
        raise RateLimiterResponseError("Redis returned an invalid rate-limit response.")

    try:
        allowed_raw = int(response[0])

        current_count = int(response[1])

        retry_after_seconds = int(response[2])

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise RateLimiterResponseError(
            "Redis returned malformed rate-limit values."
        ) from exc

    allowed = allowed_raw == 1

    remaining = max(
        policy.limit - current_count,
        0,
    )

    retry_after_seconds = max(
        retry_after_seconds,
        0,
    )

    return RateLimitDecision(
        allowed=allowed,
        limit=policy.limit,
        remaining=remaining,
        retry_after_seconds=retry_after_seconds,
        current_count=current_count,
    )


# ========================== #
# PUBLIC RATE-LIMIT API
# ========================== #


async def consume_rate_limit(
    redis: Redis,
    *,
    scope: str,
    identifier: str,
    policy: RateLimitPolicy,
) -> RateLimitDecision:
    """
    Atomically consume one unit of rate-limit capacity.

    The operation uses a Redis Lua script so checking the current
    count, incrementing it, and assigning expiry happen atomically.

    This makes the limiter safe when multiple FastAPI worker
    processes receive concurrent requests for the same identifier.

    The function returns a decision instead of raising when the
    configured limit is exceeded.

    Redis/infrastructure failures are raised separately so the
    caller can choose the appropriate failure policy.
    """

    key = _build_rate_limit_key(
        scope=scope,
        identifier=identifier,
    )

    try:
        response = await redis.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            key,
            policy.limit,
            policy.window_seconds,
        )

    except RedisError as exc:
        raise RateLimiterBackendUnavailableError(
            "Redis is unavailable for rate-limit enforcement."
        ) from exc

    return _parse_rate_limit_response(
        response,
        policy=policy,
    )


async def reset_rate_limit(
    redis: Redis,
    *,
    scope: str,
    identifier: str,
) -> bool:
    """
    Remove rate-limit state for an identifier.

    Returns True when a counter existed and was removed.

    Resetting should be explicit and used only where the calling
    domain's security rules justify it.
    """

    key = _build_rate_limit_key(
        scope=scope,
        identifier=identifier,
    )

    try:
        deleted_count = await redis.delete(key)

    except RedisError as exc:
        raise RateLimiterBackendUnavailableError(
            "Redis is unavailable for rate-limit reset."
        ) from exc

    return bool(deleted_count)
