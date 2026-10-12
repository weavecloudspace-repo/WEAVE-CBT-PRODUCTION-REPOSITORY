"""Distributed coordination primitives for staff authentication refreshes."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from uuid import UUID

from redis.exceptions import RedisError

from app.core.redis import get_redis_client

# Keep the lock comfortably beyond the configured 10-second Weave request
# timeout plus the short PostgreSQL phases on either side of the network call.
REFRESH_LOCK_TTL_SECONDS = 30
REFRESH_LOCK_WAIT_SECONDS = 3.0
REFRESH_LOCK_POLL_SECONDS = 0.05


class LocalAuthCoordinationUnavailable(RuntimeError):
    """Raised when a safe single-flight refresh lock cannot be established."""


@asynccontextmanager
async def staff_refresh_lock(session_id: UUID):
    """Serialize refresh work for one local actor session across API processes."""

    redis = get_redis_client()
    key = f"cbt:auth:refresh:{session_id}"
    owner = secrets.token_urlsafe(24)
    elapsed = 0.0
    acquired = False

    try:
        while elapsed <= REFRESH_LOCK_WAIT_SECONDS:
            acquired = bool(
                await redis.set(
                    key,
                    owner,
                    nx=True,
                    ex=REFRESH_LOCK_TTL_SECONDS,
                )
            )
            if acquired:
                break
            await asyncio.sleep(REFRESH_LOCK_POLL_SECONDS)
            elapsed += REFRESH_LOCK_POLL_SECONDS
    except RedisError as exc:
        raise LocalAuthCoordinationUnavailable(
            "Local authentication coordination is temporarily unavailable."
        ) from exc

    if not acquired:
        raise LocalAuthCoordinationUnavailable(
            "Another authentication refresh is already in progress."
        )

    try:
        yield
    finally:
        try:
            await redis.eval(
                """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    return redis.call('del', KEYS[1])
                end
                return 0
                """,
                1,
                key,
                owner,
            )
        except RedisError:
            # The lock has a bounded TTL, so a failed best-effort release cannot
            # permanently block the session.
            pass
