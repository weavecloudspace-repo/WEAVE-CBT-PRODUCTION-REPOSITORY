from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import AcademicAuthorizationError
from app.domains.audit.repository import AuditRepository
from app.domains.exams.exceptions import ExamStateError
from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.models import ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.results.models import ExamResult, ResultSyncStatus
from app.domains.results.repository import ResultRepository
from app.domains.results.retry_service import ResultRetryService
from app.domains.results.service import ResultService
from app.domains.results.sync_service import ResultSyncError, ResultSyncService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "disposition",
    [ExamResultDisposition.PENDING_REVIEW, ExamResultDisposition.APPROVED],
)
async def test_void_preserves_score_and_records_actor_reason_without_changing_set(
    disposition,
):
    db = AsyncMock()
    actor = SimpleNamespace(id=uuid4(), role="admin", is_active=True)
    result = ExamResult(
        id=uuid4(), exam_id=uuid4(), raw_score=18, sync_status=ResultSyncStatus.PENDING
    )
    control = SimpleNamespace(operation=None, result_disposition=disposition)
    with (
        patch.object(
            ResultRepository, "get_result_by_id", AsyncMock(return_value=result)
        ) as lookup,
        patch.object(
            ExamRepository,
            "get_exam_by_id",
            AsyncMock(
                return_value=SimpleNamespace(
                    id=result.exam_id, status=ExamStatus.CLOSED
                )
            ),
        ) as exam_lookup,
        patch.object(
            ExamExecutionRepository, "get_control", AsyncMock(return_value=control)
        ),
        patch.object(ResultRepository, "save_result", AsyncMock()),
        patch.object(AuditRepository, "add_event", AsyncMock()) as audit,
    ):
        await ResultService.void_result(
            db, actor=actor, result_id=result.id, reason="  Cheating confirmed  "
        )
    assert result.raw_score == 18
    assert result.void_reason == "Cheating confirmed"
    assert result.voided_at is not None
    assert result.voided_by_actor_id == actor.id
    assert control.result_disposition == disposition
    exam_lookup.assert_awaited_once_with(db, exam_id=result.exam_id, lock=True)
    assert lookup.await_args_list[-1].kwargs == {"lock": True}
    db.commit.assert_awaited_once()
    assert audit.await_args.args[1].action == "result.voided"


async def test_restore_keeps_both_decisions_in_audit_and_restores_sync_eligibility():
    from datetime import UTC, datetime

    db = AsyncMock()
    actor = SimpleNamespace(id=uuid4(), role="admin", is_active=True)
    void_time = datetime.now(UTC)
    result = ExamResult(
        id=uuid4(),
        exam_id=uuid4(),
        raw_score=18,
        sync_status=ResultSyncStatus.PENDING,
        voided_at=void_time,
        voided_by_actor_id=actor.id,
        void_reason="Initial incident",
    )
    with (
        patch.object(
            ResultRepository, "get_result_by_id", AsyncMock(return_value=result)
        ),
        patch.object(
            ExamRepository,
            "get_exam_by_id",
            AsyncMock(
                return_value=SimpleNamespace(
                    id=result.exam_id, status=ExamStatus.CLOSED
                )
            ),
        ),
        patch.object(
            ExamExecutionRepository,
            "get_control",
            AsyncMock(
                return_value=SimpleNamespace(
                    operation=None, result_disposition=ExamResultDisposition.APPROVED
                )
            ),
        ),
        patch.object(ResultRepository, "save_result", AsyncMock()),
        patch.object(AuditRepository, "add_event", AsyncMock()) as audit,
    ):
        await ResultService.restore_result(
            db, actor=actor, result_id=result.id, reason="Investigation cleared student"
        )
    assert result.raw_score == 18
    assert (
        result.voided_at is None
        and result.voided_by_actor_id is None
        and result.void_reason is None
    )
    event = audit.await_args.args[1]
    assert event.action == "result.void_restored"
    assert event.reason == "Investigation cleared student"
    assert event.metadata_json["previous_void"]["reason"] == "Initial incident"
    assert event.metadata_json["previous_void"]["voided_at"] == void_time.isoformat()
    db.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "individually_voided, set_disposition",
    [(False, ExamResultDisposition.APPROVED), (True, ExamResultDisposition.VOIDED)],
)
async def test_restore_rejects_nonvoided_result_and_whole_set_void(
    individually_voided, set_disposition
):
    db = AsyncMock()
    result = ExamResult(
        id=uuid4(),
        exam_id=uuid4(),
        sync_status=ResultSyncStatus.PENDING,
        voided_at="voided" if individually_voided else None,
    )
    with (
        patch.object(
            ResultRepository, "get_result_by_id", AsyncMock(return_value=result)
        ),
        patch.object(
            ExamRepository,
            "get_exam_by_id",
            AsyncMock(
                return_value=SimpleNamespace(
                    id=result.exam_id, status=ExamStatus.CLOSED
                )
            ),
        ),
        patch.object(
            ExamExecutionRepository,
            "get_control",
            AsyncMock(
                return_value=SimpleNamespace(
                    operation=None, result_disposition=set_disposition
                )
            ),
        ),
        pytest.raises(ExamStateError, match="individually voided|result set is voided"),
    ):
        await ResultService.restore_result(
            db,
            actor=SimpleNamespace(id=uuid4(), role="admin", is_active=True),
            result_id=result.id,
            reason="Undo",
        )
    db.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "status,batch,voided",
    [
        (ResultSyncStatus.SYNCED, uuid4(), None),
        (ResultSyncStatus.SYNCING, uuid4(), None),
        (ResultSyncStatus.FAILED, uuid4(), None),
        (ResultSyncStatus.PENDING, None, "already voided"),
    ],
)
async def test_rejects_sent_uncertain_and_already_voided_results(status, batch, voided):
    db = AsyncMock()
    result = ExamResult(
        id=uuid4(),
        exam_id=uuid4(),
        sync_status=status,
        sync_batch_id=batch,
        voided_at=voided,
    )
    with (
        patch.object(
            ResultRepository, "get_result_by_id", AsyncMock(return_value=result)
        ),
        patch.object(
            ExamRepository,
            "get_exam_by_id",
            AsyncMock(
                return_value=SimpleNamespace(
                    id=result.exam_id, status=ExamStatus.CLOSED
                )
            ),
        ),
        patch.object(
            ExamExecutionRepository,
            "get_control",
            AsyncMock(
                return_value=SimpleNamespace(
                    operation=None, result_disposition=ExamResultDisposition.APPROVED
                )
            ),
        ),
        pytest.raises(ExamStateError, match="already voided|entered synchronization"),
    ):
        await ResultService.void_result(
            db,
            actor=SimpleNamespace(id=uuid4(), role="admin", is_active=True),
            result_id=result.id,
            reason="Incident",
        )
    db.commit.assert_not_awaited()


async def test_teacher_cannot_void_results():
    db = AsyncMock()
    with pytest.raises(AcademicAuthorizationError):
        await ResultService.void_result(
            db,
            actor=SimpleNamespace(role="teacher", is_active=True),
            result_id=uuid4(),
            reason="Incident",
        )
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("reason", ["", "   ", "x" * 1025])
async def test_requires_bounded_nonblank_reason(reason):
    db = AsyncMock()
    with pytest.raises(ValueError, match="reason"):
        await ResultService.void_result(
            db,
            actor=SimpleNamespace(role="admin", is_active=True),
            result_id=uuid4(),
            reason=reason,
        )
    db.execute.assert_not_awaited()


async def test_all_sync_work_queries_exclude_individual_voids():
    db = AsyncMock()
    response = MagicMock()
    response.scalar_one_or_none.return_value = None
    response.scalars.return_value.all.return_value = []
    db.execute.return_value = response
    await ResultRepository.list_pending_results_for_exam_sync(
        db, exam_id=uuid4(), limit=100
    )
    await ResultRepository.get_retryable_sync_batch_id_for_exam(db, exam_id=uuid4())
    await ResultRepository.list_results_for_sync(db, [ResultSyncStatus.PENDING])
    with (
        patch.object(
            ExamRepository,
            "get_exam_by_id",
            AsyncMock(
                return_value=SimpleNamespace(id=uuid4(), status=ExamStatus.CLOSED)
            ),
        ),
        patch.object(
            ExamExecutionRepository,
            "get_control",
            AsyncMock(
                return_value=SimpleNamespace(
                    result_disposition=ExamResultDisposition.APPROVED
                )
            ),
        ),
        patch.object(ResultRepository, "save_results", AsyncMock()),
    ):
        await ResultRetryService.retry_detached_failures(
            db, actor=SimpleNamespace(role="admin", is_active=True), exam_id=uuid4()
        )
    for call in db.execute.await_args_list:
        sql = str(call.args[0].compile(dialect=postgresql.dialect()))
        assert "exam_results.voided_at IS NULL" in sql


async def test_payload_construction_rejects_voided_score_even_if_batch_is_corrupted():
    result = ExamResult(
        exam_id=uuid4(), sync_status=ResultSyncStatus.SYNCING, voided_at="voided"
    )
    with (
        patch.object(
            ResultRepository,
            "list_results_for_sync_batch",
            AsyncMock(return_value=[result]),
        ),
        pytest.raises(ResultSyncError, match="Voided"),
    ):
        await ResultSyncService()._prepare_batch(AsyncMock(), batch_id=uuid4())


@pytest.mark.parametrize(
    "sync_status", [ResultSyncStatus.PENDING, ResultSyncStatus.FAILED]
)
async def test_restore_route_queues_new_pending_work_after_service_commit(sync_status):
    from app.domains.results.router import restore_individual_result
    from app.domains.results.schemas import ResultVoidPayload
    from app.workers.producer import arq_producer

    result = SimpleNamespace(id=uuid4(), exam_id=uuid4(), sync_status=sync_status)
    db = AsyncMock()
    response = object()

    async def restore(*args, **kwargs):
        await db.commit()
        return result

    async def enqueue(*args, **kwargs):
        db.commit.assert_awaited_once()
        return True

    with (
        patch.object(ResultService, "restore_result", AsyncMock(side_effect=restore)),
        patch(
            "app.domains.results.router.ResultResponse.model_validate",
            return_value=response,
        ),
        patch.object(arq_producer, "enqueue", AsyncMock(side_effect=enqueue)) as queue,
    ):
        actual = await restore_individual_result(
            result_id=result.id,
            payload=ResultVoidPayload(reason="Student cleared"),
            db=db,
            actor=SimpleNamespace(role="admin"),
        )
    assert actual is response
    if sync_status == ResultSyncStatus.PENDING:
        queue.assert_awaited_once()
        assert queue.await_args.args == ("sync_exam_results", str(result.exam_id))
        assert queue.await_args.kwargs["_job_id"].startswith(
            f"weave-cbt:restore-result:{result.id}:"
        )
    else:
        queue.assert_not_awaited()
