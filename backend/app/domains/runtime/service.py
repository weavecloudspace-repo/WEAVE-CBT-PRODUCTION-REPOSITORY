"""Crash-aware, multi-instance CBT runtime heartbeat and examination recovery."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text

from app.core.database import async_session_factory
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.models import (
    Exam,
    ExamStatus,
    ExamSuspension,
    ExamSuspensionSource,
)
from app.domains.exams.repository import ExamRepository
from app.domains.runtime.models import CBTRuntimeState, RealtimeOutboxEvent
from app.domains.runtime.repository import RuntimeRepository
from app.workers.producer import arq_producer

logger = logging.getLogger(__name__)

RUNTIME_HEARTBEAT_INTERVAL_SECONDS = 5.0
RUNTIME_GAP_SUSPEND_AFTER_SECONDS = 20.0
RUNTIME_CLUSTER_LOCK_KEY = 873_421_945
RUNTIME_GAP_REASON = (
    "CBT server interruption detected. Examination paused automatically to protect "
    "candidate writing time."
)
RUNTIME_SHUTDOWN_EXAM_REASON = (
    "CBT server is shutting down. Examination paused automatically until an "
    "administrator confirms that the server and candidate devices are ready."
)


class RuntimeHeartbeatService:
    """Maintain a durable PostgreSQL heartbeat for each FastAPI runtime.

    The recovery protocol is deliberately cluster-aware because a local CBT node
    may run several API processes behind a load balancer. One process crashing
    must not pause an exam while another healthy process is still serving it.
    A machine-wide outage, OS sleep, database outage, or loss of every API
    process does suspend ACTIVE exams from the last known healthy cluster beat.

    Recovery and the new heartbeat row are committed atomically under a
    PostgreSQL transaction advisory lock. If the process dies during recovery,
    neither half is committed and the next process safely repeats it.
    """

    def __init__(self) -> None:
        self._runtime_id: UUID | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_successful_heartbeat_at: datetime | None = None
        self._last_successful_monotonic: float | None = None

    @property
    def runtime_id(self) -> UUID | None:
        return self._runtime_id

    @staticmethod
    async def _acquire_cluster_lock(db) -> None:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": RUNTIME_CLUSTER_LOCK_KEY},
        )

    @staticmethod
    async def _open_runtime_states(db) -> list[CBTRuntimeState]:
        result = await db.execute(
            select(CBTRuntimeState)
            .where(CBTRuntimeState.stopped_at.is_(None))
            .order_by(CBTRuntimeState.last_heartbeat_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    def _is_healthy_runtime(runtime: CBTRuntimeState, *, now: datetime) -> bool:
        return runtime.last_heartbeat_at >= now - timedelta(
            seconds=RUNTIME_GAP_SUSPEND_AFTER_SECONDS
        )

    @classmethod
    async def _other_healthy_runtime_exists(
        cls,
        db,
        *,
        now: datetime,
        exclude_runtime_id: UUID | None,
    ) -> bool:
        rows = await cls._open_runtime_states(db)
        return any(
            row.runtime_id != exclude_runtime_id
            and cls._is_healthy_runtime(row, now=now)
            for row in rows
        )

    @staticmethod
    async def _add_suspension_event(
        db,
        *,
        exam_id: UUID,
        reason: str,
    ) -> None:
        await RuntimeRepository.add_outbox_event(
            db,
            RealtimeOutboxEvent(
                aggregate_type="exam",
                aggregate_id=exam_id,
                event_type="exam.suspended",
                payload={"reason": reason, "source": "system"},
            ),
        )

    @classmethod
    async def _suspend_active_exams_in_transaction(
        cls,
        db,
        *,
        outage_started_at: datetime,
        reason: str,
    ) -> list[UUID]:
        """Stage system suspension without committing the caller's transaction."""

        now = datetime.now(UTC)
        result = await db.execute(
            select(Exam)
            .where(Exam.status == ExamStatus.ACTIVE)
            .order_by(Exam.id.asc())
            .with_for_update(of=Exam)
        )
        exams = list(result.scalars().all())
        suspended_ids: list[UUID] = []

        for exam in exams:
            cutoff = outage_started_at
            if exam.activated_at is not None and cutoff < exam.activated_at:
                cutoff = exam.activated_at
            cutoff = min(cutoff, now)

            open_suspension = await ExamRepository.get_open_suspension_for_exam(
                db,
                exam.id,
                lock=True,
            )
            if open_suspension is None:
                await ExamRepository.add_suspension(
                    db,
                    ExamSuspension(
                        exam_id=exam.id,
                        source=ExamSuspensionSource.SYSTEM,
                        suspended_at=cutoff,
                        suspended_by_actor_id=None,
                        reason=reason,
                    ),
                )

            exam.status = ExamStatus.SUSPENDED
            await ExamRepository.save_exam(db, exam)
            await cls._add_suspension_event(
                db,
                exam_id=exam.id,
                reason=reason,
            )
            suspended_ids.append(exam.id)

        return suspended_ids

    async def _recover_pending_worker_operations(self) -> None:
        async with async_session_factory() as db:
            (
                closing,
                cancelling,
            ) = await ExamExecutionService.list_pending_operation_exam_ids(db)
            await db.rollback()

        for exam_id in closing:
            await arq_producer.enqueue("finalize_exam_close", str(exam_id))
        for exam_id in cancelling:
            await arq_producer.enqueue("finalize_exam_cancellation", str(exam_id))

        if closing or cancelling:
            logger.warning(
                "Recovered %s closing and %s cancelling exam operation(s)",
                len(closing),
                len(cancelling),
            )

    async def start(self) -> None:
        if self._task is not None:
            return

        now = datetime.now(UTC)
        runtime_id = uuid4()
        suspended_ids: list[UUID] = []
        recovery_cutoff: datetime | None = None

        async with async_session_factory() as db:
            await self._acquire_cluster_lock(db)
            open_runtimes = await self._open_runtime_states(db)
            healthy_predecessor = any(
                self._is_healthy_runtime(row, now=now) for row in open_runtimes
            )

            if open_runtimes and not healthy_predecessor:
                # Use the freshest durable beat from the previous cluster. With
                # 5-second heartbeats this may give candidates a few seconds in
                # their favour, but can never steal outage time from them.
                recovery_cutoff = max(row.last_heartbeat_at for row in open_runtimes)
                suspended_ids = await self._suspend_active_exams_in_transaction(
                    db,
                    outage_started_at=recovery_cutoff,
                    reason=RUNTIME_GAP_REASON,
                )

            await RuntimeRepository.add_runtime_state(
                db,
                CBTRuntimeState(
                    runtime_id=runtime_id,
                    started_at=now,
                    last_heartbeat_at=now,
                ),
            )
            await db.commit()

        if recovery_cutoff is not None:
            logger.warning(
                "Recovered CBT runtime cluster after interruption from heartbeat %s; "
                "suspended exams=%s",
                recovery_cutoff.isoformat(),
                len(suspended_ids),
            )

        self._runtime_id = runtime_id
        self._last_successful_heartbeat_at = now
        self._last_successful_monotonic = time.monotonic()
        self._stop_event = asyncio.Event()

        await self._recover_pending_worker_operations()

        self._task = asyncio.create_task(
            self._run(),
            name=f"weave-cbt-runtime-heartbeat-{runtime_id}",
        )
        logger.info("CBT runtime heartbeat started: %s", runtime_id)

    async def _write_heartbeat(self, now: datetime) -> None:
        runtime_id = self._runtime_id
        if runtime_id is None:
            return
        async with async_session_factory() as db:
            runtime = await RuntimeRepository.get_runtime_state_by_id(
                db,
                runtime_id,
                lock=True,
            )
            if runtime is None or runtime.stopped_at is not None:
                await db.rollback()
                raise RuntimeError("Active CBT runtime heartbeat row is unavailable")
            runtime.last_heartbeat_at = now
            await RuntimeRepository.save_runtime_state(db, runtime)
            await db.commit()

    async def _recover_live_gap_and_heartbeat(
        self,
        *,
        last_healthy_at: datetime,
        now: datetime,
    ) -> None:
        runtime_id = self._runtime_id
        if runtime_id is None:
            return

        suspended_ids: list[UUID] = []
        async with async_session_factory() as db:
            await self._acquire_cluster_lock(db)
            another_runtime_is_healthy = await self._other_healthy_runtime_exists(
                db,
                now=now,
                exclude_runtime_id=runtime_id,
            )
            if not another_runtime_is_healthy:
                suspended_ids = await self._suspend_active_exams_in_transaction(
                    db,
                    outage_started_at=last_healthy_at,
                    reason=RUNTIME_GAP_REASON,
                )

            runtime = await RuntimeRepository.get_runtime_state_by_id(
                db,
                runtime_id,
                lock=True,
            )
            if runtime is None or runtime.stopped_at is not None:
                await db.rollback()
                raise RuntimeError("Active CBT runtime heartbeat row is unavailable")
            runtime.last_heartbeat_at = now
            await RuntimeRepository.save_runtime_state(db, runtime)
            await db.commit()

        if suspended_ids:
            logger.warning(
                "Suspended %s active examination(s) after a cluster-wide runtime gap",
                len(suspended_ids),
            )
        elif another_runtime_is_healthy:
            logger.info(
                "Runtime %s recovered from a local gap while another API runtime "
                "remained healthy; examinations were not suspended",
                runtime_id,
            )

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=RUNTIME_HEARTBEAT_INTERVAL_SECONDS,
                )
                continue
            except TimeoutError:
                pass

            now = datetime.now(UTC)
            monotonic_now = time.monotonic()
            last_at = self._last_successful_heartbeat_at
            last_mono = self._last_successful_monotonic
            gap_seconds = monotonic_now - last_mono if last_mono is not None else 0.0

            try:
                if (
                    last_at is not None
                    and gap_seconds >= RUNTIME_GAP_SUSPEND_AFTER_SECONDS
                ):
                    await self._recover_live_gap_and_heartbeat(
                        last_healthy_at=last_at,
                        now=now,
                    )
                else:
                    await self._write_heartbeat(now)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "CBT runtime heartbeat failed; a cluster-wide gap will be "
                    "recovered conservatively when PostgreSQL is reachable again"
                )
                continue

            self._last_successful_heartbeat_at = now
            self._last_successful_monotonic = monotonic_now

    async def stop(self, *, reason: str = "graceful_shutdown") -> None:
        task = self._task
        self._task = None
        self._stop_event.set()
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        runtime_id = self._runtime_id
        self._runtime_id = None
        if runtime_id is None:
            return

        now = datetime.now(UTC)
        try:
            async with async_session_factory() as db:
                await self._acquire_cluster_lock(db)
                runtime = await RuntimeRepository.get_runtime_state_by_id(
                    db,
                    runtime_id,
                    lock=True,
                )
                if runtime is None or runtime.stopped_at is not None:
                    await db.rollback()
                    return

                another_runtime_is_healthy = await self._other_healthy_runtime_exists(
                    db,
                    now=now,
                    exclude_runtime_id=runtime_id,
                )
                if not another_runtime_is_healthy:
                    await self._suspend_active_exams_in_transaction(
                        db,
                        outage_started_at=now,
                        reason=RUNTIME_SHUTDOWN_EXAM_REASON,
                    )

                stopped_at = max(now, runtime.last_heartbeat_at)
                runtime.last_heartbeat_at = stopped_at
                runtime.stopped_at = stopped_at
                runtime.shutdown_reason = reason[:500]
                await RuntimeRepository.save_runtime_state(db, runtime)
                await db.commit()
        except Exception:
            # Failing to record clean shutdown is intentionally conservative.
            # If no other process remains healthy, the next boot observes this
            # unclosed runtime and backdates suspension to its last durable beat.
            logger.exception("Could not persist clean CBT runtime shutdown")

        logger.info("CBT runtime heartbeat stopped: %s", runtime_id)


runtime_heartbeat_service = RuntimeHeartbeatService()
