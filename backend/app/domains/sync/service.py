"""Application services for Cloud -> local CBT synchronization.

Bootstrap and incremental recovery share the same projection tables. WebSocket
frames only wake this service; the durable Weave cursor log is authoritative.
All local page application is transactional: tombstones are applied first to
release partial unique scopes, then live rows are bulk-upserted parent-first.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.electives import ElectiveProjectionRepository
from app.domains.academics.models import (
    AcademicAdmin,
    AcademicClass,
    AcademicLevel,
    AcademicSession,
    AcademicSubject,
    AcademicTeacher,
    AcademicTerm,
    ArmLabel,
    AssessmentComponent,
    AssessmentScheme,
    ClassTermDepartment,
    Curriculum,
    CurriculumSubject,
    CurriculumSubjectDepartment,
    Department,
    SchoolProfile,
    StudentElectiveSelection,
    StudentEnrollment,
    TeacherAssignment,
)
from app.domains.academics.repository import AcademicRepository
from app.domains.auth.service import LocalAuthService
from app.domains.node.identity_store import node_identity_store
from app.domains.sync.invalidation import SyncInvalidationRepository
from app.domains.sync.repository import SyncRepository
from app.domains.sync.schemas import SyncReconcileResponse, SyncStatusResponse
from app.integrations.weave.academics import (
    WeaveAcademicsGateway,
    weave_academics_gateway,
)
from app.integrations.weave.exceptions import WeaveRequestRejectedError
from app.integrations.weave.schemas import (
    SYNC_SCHEMA_VERSION,
    WeaveAcademicBootstrap,
    WeaveAcademicLevelSnapshot,
    WeaveAcademicSessionSnapshot,
    WeaveAcademicTermSnapshot,
    WeaveAdminSnapshot,
    WeaveArmLabelSnapshot,
    WeaveAssessmentComponentSnapshot,
    WeaveAssessmentSchemeSnapshot,
    WeaveClassSnapshot,
    WeaveClassTermDepartmentSnapshot,
    WeaveCurriculumSnapshot,
    WeaveCurriculumSubjectDepartmentSnapshot,
    WeaveCurriculumSubjectSnapshot,
    WeaveDepartmentSnapshot,
    WeaveStudentElectiveSelectionSnapshot,
    WeaveStudentEnrollmentSnapshot,
    WeaveSubjectSnapshot,
    WeaveSyncChange,
    WeaveTeacherAssignmentSnapshot,
    WeaveTeacherSnapshot,
)

logger = logging.getLogger(__name__)

SYNC_SCOPE = "academics"
DEFAULT_PAGE_SIZE = 500

ENTITY_SCHEMAS: dict[str, type[BaseModel]] = {
    "academic_session": WeaveAcademicSessionSnapshot,
    "academic_term": WeaveAcademicTermSnapshot,
    "academic_level": WeaveAcademicLevelSnapshot,
    "arm_label": WeaveArmLabelSnapshot,
    "department": WeaveDepartmentSnapshot,
    "class": WeaveClassSnapshot,
    "class_term_department": WeaveClassTermDepartmentSnapshot,
    "subject": WeaveSubjectSnapshot,
    "curriculum": WeaveCurriculumSnapshot,
    "curriculum_subject": WeaveCurriculumSubjectSnapshot,
    "curriculum_subject_department": WeaveCurriculumSubjectDepartmentSnapshot,
    "assessment_scheme": WeaveAssessmentSchemeSnapshot,
    "assessment_component": WeaveAssessmentComponentSnapshot,
    "admin": WeaveAdminSnapshot,
    "teacher": WeaveTeacherSnapshot,
    "teacher_assignment": WeaveTeacherAssignmentSnapshot,
    "student_enrollment": WeaveStudentEnrollmentSnapshot,
    "student_elective_selection": WeaveStudentElectiveSelectionSnapshot,
}

ENTITY_MODELS: dict[str, type] = {
    "academic_session": AcademicSession,
    "academic_term": AcademicTerm,
    "academic_level": AcademicLevel,
    "arm_label": ArmLabel,
    "department": Department,
    "class": AcademicClass,
    "class_term_department": ClassTermDepartment,
    "subject": AcademicSubject,
    "curriculum": Curriculum,
    "curriculum_subject": CurriculumSubject,
    "curriculum_subject_department": CurriculumSubjectDepartment,
    "assessment_scheme": AssessmentScheme,
    "assessment_component": AssessmentComponent,
    "admin": AcademicAdmin,
    "teacher": AcademicTeacher,
    "teacher_assignment": TeacherAssignment,
    "student_enrollment": StudentEnrollment,
    "student_elective_selection": StudentElectiveSelection,
}

UPSERT_ORDER = tuple(ENTITY_MODELS)
BOOTSTRAP_SECTIONS = (
    ("academic_session", "sessions"),
    ("academic_term", "terms"),
    ("academic_level", "levels"),
    ("arm_label", "arm_labels"),
    ("department", "departments"),
    ("class", "classes"),
    ("class_term_department", "class_term_departments"),
    ("subject", "subjects"),
    ("curriculum", "curricula"),
    ("curriculum_subject", "curriculum_subjects"),
    ("curriculum_subject_department", "curriculum_subject_departments"),
    ("assessment_scheme", "assessment_schemes"),
    ("assessment_component", "assessment_components"),
    ("admin", "admins"),
    ("teacher", "teachers"),
    ("teacher_assignment", "teacher_assignments"),
    ("student_enrollment", "student_enrollments"),
    ("student_elective_selection", "student_elective_selections"),
)


class SyncContractViolation(RuntimeError):
    """Raised when a Weave response contradicts local identity/cursor state."""


class SyncService:
    def __init__(
        self, gateway: WeaveAcademicsGateway = weave_academics_gateway
    ) -> None:
        self.gateway = gateway

    @staticmethod
    def _values(snapshot: BaseModel) -> dict[str, Any]:
        return snapshot.model_dump(exclude={"id"})

    @staticmethod
    def _row(snapshot: BaseModel) -> dict[str, Any]:
        return {"id": snapshot.id, **SyncService._values(snapshot)}  # type: ignore[attr-defined]

    @staticmethod
    async def _status(db: AsyncSession) -> SyncStatusResponse:
        state = await SyncRepository.get_state(db, SYNC_SCOPE)
        if state is None:
            return SyncStatusResponse(
                scope=SYNC_SCOPE,
                schema_version=SYNC_SCHEMA_VERSION,
                cursor=0,
            )
        return SyncStatusResponse.model_validate(state, from_attributes=True)

    async def get_status(self, db: AsyncSession) -> SyncStatusResponse:
        return await self._status(db)

    async def _bulk_install_bootstrap(
        self,
        db: AsyncSession,
        payload: WeaveAcademicBootstrap,
    ) -> None:
        await AcademicRepository.bulk_upsert_projections(
            db,
            SchoolProfile,
            [self._row(payload.school)],
            synced_at=payload.metadata.generated_at,
        )
        await AcademicRepository.mark_all_projection_rows_deleted(
            db,
            deleted_at=payload.metadata.generated_at,
        )
        # Student elective selections were introduced after the original
        # projection-model registry. Tombstone them explicitly so a bootstrap
        # cannot leave a stale local choice that Weave no longer returns.
        await ElectiveProjectionRepository.mark_all_deleted(
            db,
            deleted_at=payload.metadata.generated_at,
        )
        for entity_type, attribute in BOOTSTRAP_SECTIONS:
            snapshots = getattr(payload, attribute)
            await AcademicRepository.bulk_upsert_projections(
                db,
                ENTITY_MODELS[entity_type],
                [self._row(snapshot) for snapshot in snapshots],
                synced_at=payload.metadata.generated_at,
            )

        # A full bootstrap may replace enrollment/elective truth wholesale. Any
        # roster prepared before execution must be rebuilt from the new snapshot.
        await SyncInvalidationRepository.mark_pre_execution_rosters_stale(db)

        # Weave omits staff who are no longer authorized from the active
        # bootstrap. Reconcile local trust only after the authoritative
        # projection has been fully installed.
        await LocalAuthService.reconcile_synced_staff_trust(
            db,
            revalidated_at=payload.metadata.generated_at,
        )

    async def bootstrap(
        self,
        db: AsyncSession,
        *,
        force: bool = False,
    ) -> SyncReconcileResponse:
        """Fetch and atomically install one complete current Weave snapshot."""

        identity = node_identity_store.load()
        payload = await self.gateway.fetch_bootstrap(
            server_credential=identity.server_credential,
        )
        self._validate_bootstrap_identity(
            payload,
            identity.tenant_id,
            identity.server_id,
        )

        previous_state = await SyncRepository.get_state(db, SYNC_SCOPE)
        previous_cursor = previous_state.cursor if previous_state is not None else 0
        await db.rollback()

        applied_at = datetime.now(UTC)
        installed_snapshot = False
        try:
            async with db.begin():
                await SyncRepository.acquire_apply_lock(db)
                state = await SyncRepository.get_or_create_state(
                    db,
                    SYNC_SCOPE,
                    lock=True,
                )
                state.last_attempted_at = applied_at

                if state.cursor > payload.metadata.cursor or (
                    not force
                    and state.schema_version == SYNC_SCHEMA_VERSION
                    and state.bootstrap_completed_at is not None
                    and state.cursor >= payload.metadata.cursor
                ):
                    state.last_error = None
                    await SyncRepository.save_state(db, state)
                else:
                    await self._bulk_install_bootstrap(db, payload)
                    state.schema_version = payload.metadata.schema_version
                    state.cursor = payload.metadata.cursor
                    state.bootstrap_snapshot_id = payload.metadata.snapshot_id
                    state.bootstrap_completed_at = applied_at
                    state.last_successful_at = applied_at
                    state.last_error = None
                    await SyncRepository.save_state(db, state)
                    installed_snapshot = True
        except Exception as exc:
            await self._record_failure(db, str(exc))
            raise

        status = await self._status(db)
        return SyncReconcileResponse(
            **status.model_dump(),
            previous_cursor=previous_cursor,
            changes_applied=0,
            bootstrapped=installed_snapshot,
        )

    @staticmethod
    def _validate_delta(
        cursor: int, changes: list[WeaveSyncChange], next_cursor: int
    ) -> None:
        previous = cursor
        for change in changes:
            if change.cursor <= previous:
                raise SyncContractViolation(
                    "Weave returned non-increasing synchronization changes."
                )
            previous = change.cursor
        if changes:
            if next_cursor != previous:
                raise SyncContractViolation(
                    "Weave delta next_cursor does not match the last returned change."
                )
        elif next_cursor != cursor:
            raise SyncContractViolation(
                "Weave returned an empty delta that advanced the synchronization cursor."
            )

    @staticmethod
    def _coalesce_changes(changes: list[WeaveSyncChange]) -> list[WeaveSyncChange]:
        latest: dict[tuple[str, UUID], WeaveSyncChange] = {}
        for change in changes:
            latest[(change.entity_type, change.entity_id)] = change
        return sorted(latest.values(), key=lambda change: change.cursor)

    async def _apply_delta_page(
        self,
        db: AsyncSession,
        changes: list[WeaveSyncChange],
    ) -> None:
        """Apply final page state with tombstones first and parent-first upserts."""

        effective = self._coalesce_changes(changes)
        tombstones: dict[str, list[WeaveSyncChange]] = defaultdict(list)
        upserts: dict[str, list[tuple[WeaveSyncChange, BaseModel]]] = defaultdict(list)

        for change in effective:
            if change.schema_version != SYNC_SCHEMA_VERSION:
                raise SyncContractViolation(
                    f"Unsupported Weave sync schema version {change.schema_version}."
                )
            if change.operation == "deleted":
                tombstones[change.entity_type].append(change)
                continue

            snapshot = ENTITY_SCHEMAS[change.entity_type].model_validate(change.payload)
            if snapshot.id != change.entity_id:  # type: ignore[attr-defined]
                raise SyncContractViolation(
                    f"Sync entity id mismatch for {change.entity_type} at cursor {change.cursor}."
                )
            upserts[change.entity_type].append((change, snapshot))

        for entity_type in reversed(UPSERT_ORDER):
            entries = tombstones.get(entity_type)
            if not entries:
                continue
            await AcademicRepository.bulk_tombstone_projections(
                db,
                ENTITY_MODELS[entity_type],
                [entry.entity_id for entry in entries],
                deleted_at=max(entry.occurred_at for entry in entries),
            )

        for entity_type in UPSERT_ORDER:
            entries = upserts.get(entity_type)
            if not entries:
                continue
            await AcademicRepository.bulk_upsert_projections(
                db,
                ENTITY_MODELS[entity_type],
                [self._row(snapshot) for _, snapshot in entries],
                synced_at=max(change.occurred_at for change, _ in entries),
            )

        eligibility_entities = {
            "student_enrollment",
            "student_elective_selection",
            "curriculum_subject",
        }
        if any(change.entity_type in eligibility_entities for change in effective):
            await SyncInvalidationRepository.mark_pre_execution_rosters_stale(db)

        staff_changes = [
            change for change in effective if change.entity_type in {"admin", "teacher"}
        ]
        if staff_changes:
            await LocalAuthService.reconcile_synced_staff_trust(
                db,
                revalidated_at=max(change.occurred_at for change in staff_changes),
            )

    async def reconcile(self, db: AsyncSession) -> SyncReconcileResponse:
        """Recover every durable Weave change after the local committed cursor."""

        identity = node_identity_store.load()
        state = await SyncRepository.get_state(db, SYNC_SCOPE)
        if (
            state is None
            or state.bootstrap_completed_at is None
            or state.schema_version != SYNC_SCHEMA_VERSION
        ):
            await db.rollback()
            return await self.bootstrap(db, force=True)

        previous_cursor = state.cursor
        cursor = state.cursor
        await db.rollback()
        changes_applied = 0

        try:
            while True:
                try:
                    delta = await self.gateway.fetch_changes(
                        server_credential=identity.server_credential,
                        after_cursor=cursor,
                        limit=DEFAULT_PAGE_SIZE,
                    )
                except WeaveRequestRejectedError as exc:
                    if exc.status_code == 409:
                        logger.info(
                            "Local cursor %s is outside Weave retention; bootstrapping.",
                            cursor,
                        )
                        await db.rollback()
                        return await self.bootstrap(db, force=True)
                    raise

                if delta.from_cursor != cursor:
                    raise SyncContractViolation(
                        f"Weave delta started at {delta.from_cursor}; local cursor is {cursor}."
                    )
                if delta.next_cursor < cursor:
                    raise SyncContractViolation(
                        "Weave synchronization cursor moved backwards."
                    )
                self._validate_delta(cursor, delta.changes, delta.next_cursor)

                attempted_at = datetime.now(UTC)
                cursor_was_advanced_elsewhere = False
                async with db.begin():
                    await SyncRepository.acquire_apply_lock(db)
                    locked_state = await SyncRepository.get_or_create_state(
                        db,
                        SYNC_SCOPE,
                        lock=True,
                    )

                    if locked_state.cursor < cursor:
                        raise SyncContractViolation(
                            "Local synchronization cursor moved backwards."
                        )
                    if locked_state.cursor != cursor:
                        cursor = locked_state.cursor
                        cursor_was_advanced_elsewhere = True
                    else:
                        locked_state.last_attempted_at = attempted_at
                        await self._apply_delta_page(db, delta.changes)
                        locked_state.cursor = delta.next_cursor
                        locked_state.schema_version = SYNC_SCHEMA_VERSION
                        locked_state.last_successful_at = attempted_at
                        locked_state.last_error = None
                        await SyncRepository.save_state(db, locked_state)

                if cursor_was_advanced_elsewhere:
                    continue

                changes_applied += len(delta.changes)
                cursor = delta.next_cursor
                if not delta.has_more:
                    break
        except (IntegrityError, SyncContractViolation) as exc:
            logger.warning(
                "Incremental CBT sync could not be safely applied; forcing bootstrap: %s",
                exc,
            )
            await db.rollback()
            return await self.bootstrap(db, force=True)
        except Exception as exc:
            await self._record_failure(db, str(exc))
            raise

        status = await self._status(db)
        return SyncReconcileResponse(
            **status.model_dump(),
            previous_cursor=previous_cursor,
            changes_applied=changes_applied,
            bootstrapped=False,
        )

    @staticmethod
    def _validate_bootstrap_identity(
        payload: WeaveAcademicBootstrap,
        tenant_id: UUID,
        server_id: UUID,
    ) -> None:
        if payload.school.id != tenant_id:
            raise SyncContractViolation(
                "Weave bootstrap belongs to an unexpected tenant."
            )
        if payload.server.id != server_id:
            raise SyncContractViolation(
                "Weave bootstrap belongs to an unexpected CBT server."
            )

    @staticmethod
    async def _record_failure(db: AsyncSession, message: str) -> None:
        await db.rollback()
        async with db.begin():
            await SyncRepository.acquire_apply_lock(db)
            state = await SyncRepository.get_or_create_state(
                db,
                SYNC_SCOPE,
                lock=True,
            )
            state.last_attempted_at = datetime.now(UTC)
            state.last_error = message[:1024]
            await SyncRepository.save_state(db, state)


sync_service = SyncService()
