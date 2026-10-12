# ==========================#
# backend.app.core.redis
# ==========================#


"""
Asynchronous Redis infrastructure for the Weave CBT runtime

Redis is used for temporary and coordination-oriented state such as:

- caching
- rate limiting
- distributed coordination
- short-lived locks
- background worker infrastructure



Redis is NOT a durable source of truth

Durable examination state must remain in PostgreSQL , including:

- questions
- examinations
- attempts
- candidate answers
- examination results
- local authentication sessions
- synchronization state


THE CBT application must therefore never rely on Redis as the only
location containing examination - critical data
"""

from typing import Annotated, TypeAlias

from fastapi import Depends
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.settings import settings

# ==========================#
# EXCEPTIONS
# ==========================#


class RedisInfrastructureError(Exception):
    """Base exception for CBT Redis infrastructure failures"""


class RedisUnavailableError(RedisInfrastructureError):
    """Raised when the local Redis service cannot be reached."""


# ==========================#
# REDIS CLIENT
# ==========================#

redis_client: Redis = Redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
    socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
    socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
    health_check_interval=settings.REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
    max_connections=settings.REDIS_MAX_CONNECTIONS,
)


# ==========================#
# REDIS CLIENT ACCESS
# ==========================#
def get_redis_client() -> Redis:
    """
    Return the process's shared asynchronous Redis client

    The Redis client owns an internal connection pool and should
    be reused rather than recreated for every request
    """
    return redis_client


# ========================== #
# REDIS HEALTH
# ========================== #


async def check_redis_connection() -> bool:
    """
    Check whether Redis is currently reachable.

    Redis is supporting infrastructure rather than the durable
    examination store.

    A failed check therefore reports Redis as unavailable without
    deciding whether the entire CBT API should stop.

    Application startup/lifespan logic is responsible for deciding
    how to handle degraded Redis availability.
    """

    try:
        return bool(await redis_client.ping())

    except RedisError:
        return False


async def require_redis_connection() -> None:
    """
    Verify that Redis is reachable and raise a typed infrastructure
    exception when it is unavailable.

    Use this only for operations that genuinely require Redis.

    Examination-critical workflows should not depend exclusively
    on this function because PostgreSQL remains the durable source
    of truth.
    """

    is_available = await check_redis_connection()

    if not is_available:
        raise RedisUnavailableError("The local CBT Redis service is unavailable.")


# ========================== #
# REDIS SHUTDOWN
# ========================== #


async def close_redis_client() -> None:
    """
    Close this process's Redis client and its connection pool.

    Each FastAPI worker process owns its own Redis client and should
    close it during graceful application shutdown.
    """

    await redis_client.aclose()


# ========================== #
# FASTAPI TYPE ALIASES
# ========================== #

RedisSession: TypeAlias = Annotated[
    Redis,
    Depends(get_redis_client),
]
