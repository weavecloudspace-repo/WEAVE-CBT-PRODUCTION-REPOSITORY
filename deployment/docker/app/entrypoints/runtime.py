"""Unified production entry point for the compiled WEAVE CBT runtime."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable


def run_api() -> None:
    """Start the WEAVE CBT FastAPI server."""
    import uvicorn
    from app.core.settings import settings
    from app.main import app

    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )


def run_worker() -> None:
    """Start the WEAVE CBT ARQ worker."""
    from app.workers.worker import WorkerSettings
    from arq.worker import run_worker

    run_worker(WorkerSettings)


def run_bootstrap() -> None:
    """Initialize a fresh database or validate an existing schema."""
    from app.core.database import dispose_database_engine
    from app.core.database_bootstrap import bootstrap_database

    async def initialize() -> None:
        try:
            await bootstrap_database()
        finally:
            await dispose_database_engine()

    asyncio.run(initialize())


COMMANDS: dict[str, Callable[[], None]] = {
    "api": run_api,
    "worker": run_worker,
    "bootstrap": run_bootstrap,
}


def main() -> None:
    """Dispatch the compiled runtime to the requested process mode."""
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        commands = " | ".join(COMMANDS)
        raise SystemExit(f"Usage: weave-cbt <{commands}>")

    mode = sys.argv[1]
    from app.core.error_logging import configure_error_logging
    configure_error_logging(mode)
    try:
        COMMANDS[mode]()
    except Exception:
        import logging
        logging.getLogger("weave.runtime").exception(
            "Service terminated unexpectedly", extra={"operation": mode}
        )
        raise


if __name__ == "__main__":
    main()
