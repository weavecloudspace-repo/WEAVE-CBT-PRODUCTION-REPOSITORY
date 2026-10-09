from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.database import check_database_connection, dispose_database_engine
from app.core.database_bootstrap import verify_database_schema
from app.core.frontend import register_frontend_routes
from app.core.integration_errors import register_weave_integration_error_handlers
from app.core.redis import close_redis_client
from app.core.settings import settings
from app.domains.academics.router import router as academic_router
from app.domains.ai.router import router as ai_router
from app.domains.attempts.router import exam_router as exam_attempts_router
from app.domains.attempts.router import operator_router as attempts_router
from app.domains.attempts.router import student_router as student_attempts_router
from app.domains.auth.router import router as auth_router
from app.domains.auth.student_router import router as student_auth_router
from app.domains.branding.router import router as branding_router
from app.domains.candidates.makeup_router import router as makeup_router
from app.domains.candidates.router import router as candidates_router
from app.domains.exams.execution_router import router as exam_execution_router
from app.domains.exams.question_authoring_router import (
    router as exam_question_authoring_router,
)
from app.domains.exams.read_router import router as exam_read_router
from app.domains.exams.router import router as exams_router
from app.domains.exams.timetable_router import router as timetable_router
from app.domains.media.router import router as media_router
from app.domains.node.router import router as node_router
from app.domains.questions.ai_router import router as question_ai_router
from app.domains.questions.exceptions import QuestionConflictError
from app.domains.questions.management_router import router as question_management_router
from app.domains.questions.router import router as questions_router
from app.domains.results.router import router as results_router
from app.domains.runtime.service import runtime_heartbeat_service
from app.domains.sync.router import router as sync_router
from app.domains.sync.supervisor import sync_supervisor
from app.integrations.weave.client import weave_client
from app.workers.producer import arq_producer


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start durable runtime recovery and non-blocking coordination."""

    await check_database_connection()
    await verify_database_schema()
    await arq_producer.start()
    await runtime_heartbeat_service.start()

    sync_task = asyncio.create_task(
        sync_supervisor.run(), name="weave-cbt-sync-supervisor"
    )

    try:
        yield
    finally:
        await sync_supervisor.stop()
        sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task
        await runtime_heartbeat_service.stop()
        await arq_producer.close()
        await weave_client.close()
        await close_redis_client()
        await dispose_database_engine()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_weave_integration_error_handlers(app)


@app.exception_handler(QuestionConflictError)
async def question_conflict_handler(
    _request: Request,
    exc: QuestionConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


for router in (
    node_router,
    branding_router,
    auth_router,
    student_auth_router,
    ai_router,
    sync_router,
    media_router,
    academic_router,
    question_management_router,
    question_ai_router,
    questions_router,
    exams_router,
    exam_question_authoring_router,
    exam_read_router,
    exam_execution_router,
    timetable_router,
    candidates_router,
    makeup_router,
    student_attempts_router,
    exam_attempts_router,
    attempts_router,
    results_router,
):
    app.include_router(router, prefix=settings.API_V1_PREFIX)


register_frontend_routes(app)
