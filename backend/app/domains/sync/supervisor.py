"""Singleton near-real-time supervisor for Weave -> CBT synchronization.

PostgreSQL session advisory leadership guarantees that exactly one local API
process owns the Cloud socket. The WebSocket is only a low-latency cursor wake
path; durable HTTP reconciliation remains authoritative.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.core.database import async_session_factory, engine
from app.domains.branding.service import branding_service
from app.domains.node.exceptions import (
    NodeIdentityNotFoundError,
    NodeIdentityStorageError,
)
from app.domains.node.identity_store import node_identity_store
from app.domains.sync.service import sync_service
from app.integrations.weave.academics import weave_academics_gateway
from app.workers.roster_delivery import enqueue_roster_reconciliation_after_sync

logger = logging.getLogger(__name__)

SYNC_LEADER_LOCK_KEY = 873_421_946
LEADER_RETRY_SECONDS = 5
LEADER_HEARTBEAT_SECONDS = 10
RECONCILE_FALLBACK_SECONDS = 60
RECONNECT_MIN_SECONDS = 2
RECONNECT_MAX_SECONDS = 30


class SyncSupervisor:
    """Maintain one Cloud synchronization owner across local API processes."""

    def __init__(self) -> None:
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            try:
                identity = node_identity_store.load()
            except NodeIdentityNotFoundError:
                await self._sleep(5)
                continue
            except NodeIdentityStorageError:
                logger.exception("Unable to load persistent CBT installation identity.")
                await self._sleep(15)
                continue

            try:
                async with engine.connect() as leader_connection:
                    if not await self._acquire_leadership(leader_connection):
                        await self._sleep(LEADER_RETRY_SECONDS)
                        continue
                    try:
                        await self._run_as_leader(
                            credential=identity.server_credential.get_secret_value(),
                            leader_connection=leader_connection,
                        )
                    finally:
                        await self._release_leadership(leader_connection)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("CBT sync leadership loop failed.")
                await self._sleep(LEADER_RETRY_SECONDS)

    async def _run_as_leader(
        self,
        *,
        credential: str,
        leader_connection: AsyncConnection,
    ) -> None:
        backoff = RECONNECT_MIN_SECONDS
        while not self._stop.is_set():
            try:
                await self._check_leadership_connection(leader_connection)
                current_cursor = await self._reconcile_once()
                await self._stream(
                    credential=credential,
                    current_cursor=current_cursor,
                    leader_connection=leader_connection,
                )
                backoff = RECONNECT_MIN_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Weave CBT live synchronization supervisor failed.")
                await self._sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_SECONDS)

    async def _stream(
        self,
        *,
        credential: str,
        current_cursor: int,
        leader_connection: AsyncConnection,
    ) -> int:
        loop = asyncio.get_running_loop()
        last_reconcile_at = loop.time()
        last_leader_check_at = loop.time()

        async with connect(
            weave_academics_gateway.stream_url(),
            additional_headers={"Authorization": f"Bearer {credential}"},
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            proxy=None,
        ) as websocket:
            while not self._stop.is_set():
                now = loop.time()
                if now - last_leader_check_at >= LEADER_HEARTBEAT_SECONDS:
                    await self._check_leadership_connection(leader_connection)
                    last_leader_check_at = now

                if now - last_reconcile_at >= RECONCILE_FALLBACK_SECONDS:
                    current_cursor = await self._reconcile_once()
                    last_reconcile_at = loop.time()

                try:
                    raw_message = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=LEADER_HEARTBEAT_SECONDS,
                    )
                except TimeoutError:
                    continue
                except ConnectionClosed:
                    return current_cursor

                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8")
                try:
                    message = json.loads(raw_message)
                except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
                    logger.warning("Ignoring malformed Weave CBT WebSocket frame.")
                    continue
                if not isinstance(message, dict):
                    continue

                message_type = message.get("type")
                if message_type in {"connection.ready", "cbt.sync.available"}:
                    advertised_cursor = message.get("cursor")
                    if (
                        isinstance(advertised_cursor, int)
                        and advertised_cursor > current_cursor
                    ):
                        current_cursor = await self._reconcile_once()
                        last_reconcile_at = loop.time()
                elif message_type == "cbt.sync.check":
                    current_cursor = await self._reconcile_once()
                    last_reconcile_at = loop.time()

        return current_cursor

    @staticmethod
    async def _acquire_leadership(connection: AsyncConnection) -> bool:
        acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": SYNC_LEADER_LOCK_KEY},
            )
        )
        await connection.commit()
        return acquired

    @staticmethod
    async def _release_leadership(connection: AsyncConnection) -> None:
        try:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": SYNC_LEADER_LOCK_KEY},
            )
            await connection.commit()
        except SQLAlchemyError:
            logger.warning(
                "Unable to release sync leadership; connection closure will release it.",
                exc_info=True,
            )

    @staticmethod
    async def _check_leadership_connection(connection: AsyncConnection) -> None:
        await connection.execute(text("SELECT 1"))
        await connection.commit()

    @staticmethod
    async def _reconcile_once() -> int:
        async with async_session_factory() as db:
            result = await sync_service.reconcile(db)
            # The sync service has committed any enrollment-driven STALE roster
            # transitions by this point. Deliver reconciliation immediately;
            # the maintenance cron remains the durable fallback if enqueueing
            # is unavailable.
            await enqueue_roster_reconciliation_after_sync(result)
            await branding_service.refresh_best_effort(db)
            return result.cursor

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)


sync_supervisor = SyncSupervisor()
