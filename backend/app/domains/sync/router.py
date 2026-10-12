"""Local administrator endpoints for synchronization recovery and health."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from app.core.database import DbSession
from app.domains.auth.dependencies import CurrentLocalAdmin
from app.domains.sync.schemas import SyncReconcileResponse, SyncStatusResponse
from app.domains.sync.service import sync_service
from app.workers.roster_delivery import enqueue_roster_reconciliation_after_sync

router = APIRouter(prefix="/sync", tags=["Synchronization"])


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    db: DbSession,
    _admin: CurrentLocalAdmin,
    response: Response,
) -> SyncStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    return await sync_service.get_status(db)


@router.post("/reconcile", response_model=SyncReconcileResponse)
async def reconcile_now(
    db: DbSession,
    _admin: CurrentLocalAdmin,
    response: Response,
    force_full: bool = Query(
        default=False,
        description=(
            "Reinstall the complete authoritative Weave academic snapshot instead of "
            "only applying durable changes after the local cursor."
        ),
    ),
) -> SyncReconcileResponse:
    """Manually synchronize the local CBT projection from authoritative Weave APIs.

    The default path is an efficient cursor reconciliation: fetch and apply every
    durable Weave change after the local committed cursor. ``force_full=true`` is
    the recovery path for intentionally reinstalling the current complete academic
    snapshot when an operator needs a full resync.
    """

    response.headers["Cache-Control"] = "no-store"
    if force_full:
        result = await sync_service.bootstrap(db, force=True)
    else:
        result = await sync_service.reconcile(db)

    # The synchronization transaction has committed before this point. Any
    # SEALED + READY rosters invalidated by enrollment changes are therefore
    # durably STALE before we ask Redis/ARQ to reconcile them.
    await enqueue_roster_reconciliation_after_sync(result)
    return result
