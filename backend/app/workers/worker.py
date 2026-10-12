"""ARQ worker configuration for Weave CBT background jobs."""

from __future__ import annotations

import logging
from typing import ClassVar

from arq import cron

from app.core.database import engine
from app.core.database_bootstrap import bootstrap_database
from app.integrations.weave.client import weave_client
from app.workers.broker import arq_redis_settings
from app.workers.candidates import prepare_exam_roster, reconcile_exam_roster
from app.workers.exams import (
    evaluate_exam_completion,
    finalize_exam_cancellation,
    finalize_exam_close,
    finalize_expired_attempts,
)
from app.workers.maintenance import recover_background_work
from app.workers.results import sync_exam_results

logger = logging.getLogger(__name__)


async def on_startup(_ctx: dict) -> None:
    await bootstrap_database()
    logger.info("Weave CBT background worker started")


async def on_shutdown(_ctx: dict) -> None:
    await weave_client.close()
    await engine.dispose()
    logger.info("Weave CBT background worker stopped")


class WorkerSettings:
    """ARQ configuration for the Weave CBT background worker."""

    redis_settings = arq_redis_settings

    functions: ClassVar[list] = [
        prepare_exam_roster,
        reconcile_exam_roster,
        evaluate_exam_completion,
        finalize_exam_close,
        finalize_exam_cancellation,
        finalize_expired_attempts,
        sync_exam_results,
    ]

    cron_jobs: ClassVar[list] = [
        cron(
            coroutine=recover_background_work,
            minute=set(range(0, 60, 2)),
            second=0,
            run_at_startup=True,
            unique=True,
        )
    ]

    max_jobs = 10
    job_timeout = 30 * 60
    max_tries = 5
    keep_result = 60
    on_startup = on_startup
    on_shutdown = on_shutdown
