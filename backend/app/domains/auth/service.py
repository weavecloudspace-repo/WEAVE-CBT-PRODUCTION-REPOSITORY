# =========================== #
#       auth/service.py       #
# =========================== #

"""Application service for local CBT staff authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    StoredSecretDecryptionError,
    create_local_access_token,
    decrypt_local_secret,
    encrypt_local_secret,
    generate_refresh_token,
    hash_refresh_token,
)
from app.domains.academics.repository import AcademicRepository
from app.domains.auth.coordination import staff_refresh_lock
from app.domains.auth.models import (
    WEAVE_AUTH_STATE_DEGRADED,
    WEAVE_AUTH_STATE_LEGACY,
    WEAVE_AUTH_STATE_REFRESH_PENDING,
    WEAVE_AUTH_STATE_REVOKED,
    WEAVE_AUTH_STATE_SYNCED,
    LocalActor,
    LocalActorSession,
    LocalRefreshToken,
)
from app.domains.auth.repository import AuthRepository
from app.domains.auth.schemas import StaffLoginRequest
from app.domains.node.identity_store import node_identity_store
from app.integrations.weave.auth import weave_auth_gateway
from app.integrations.weave.auth_schemas import (
    WeaveActorTokenPair,
    WeaveStaffAuthResult,
    WeaveStaffLoginRequest,
)
from app.integrations.weave.exceptions import (
    WeaveContractError,
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)

INVALID_LOCAL_STAFF_SESSION = "Local staff session is invalid or expired."
SYNC_TRUST_REVOKED_REASON = "Weave staff authorization is no longer active."
REFRESH_REUSE_REASON = "Refresh token reuse detected."
LOGOUT_REASON = "Staff logged out."
WEAVE_AUTH_REJECTED_REASON = "Weave actor authorization was rejected."
LEGACY_SESSION_REASON = "Staff session predates Weave authorization synchronization."

# Offline local access renewal reuses the most recently observed Weave access
# window. This cap prevents a malformed cloud response from creating an
# excessively long degraded local JWT.
MAX_DEGRADED_ACCESS_WINDOW = timedelta(hours=1)
MIN_DEGRADED_ACCESS_WINDOW = timedelta(minutes=1)


class LocalSessionAuthenticationError(RuntimeError):
    """Raised when a local staff session or refresh token cannot be trusted."""


@dataclass(frozen=True)
class LocalLoginResult:
    """Internal result of a successful local staff login or refresh."""

    access_token: str
    refresh_token: str
    actor: LocalActor
    access_token_expires_at: datetime
    session_expires_at: datetime
    cloud_auth_state: str


@dataclass(frozen=True)
class _PreparedCloudRefresh:
    session_id: UUID
    cloud_operation_id: UUID
    cloud_refresh_token: str


class LocalAuthService:
    """Orchestrate one local session around one Weave actor authorization."""

    @staticmethod
    async def login_staff(
        db: AsyncSession,
        *,
        payload: StaffLoginRequest,
    ) -> LocalLoginResult:
        """Authenticate through Weave and mirror its authorization clocks locally."""

        installation = node_identity_store.load()

        # Never hold PostgreSQL open while waiting on the internet.
        weave_actor = await weave_auth_gateway.authenticate_staff(
            payload=WeaveStaffLoginRequest(
                email=payload.email,
                password=payload.password,
            ),
            server_credential=installation.server_credential,
        )

        LocalAuthService._validate_weave_identity(
            weave_actor=weave_actor,
            tenant_id=installation.tenant_id,
        )

        now = datetime.now(UTC)
        access_expires_at, hard_expires_at = (
            LocalAuthService._validate_token_pair_times(
                access_expires_at=weave_actor.access_token_expires_at,
                refresh_expires_at=weave_actor.refresh_token_expires_at,
                now=now,
            )
        )
        session_id = uuid4()

        async with db.begin():
            actor = await LocalAuthService._upsert_actor(
                db,
                weave_actor=weave_actor,
                now=now,
            )

            actor_session = LocalActorSession(
                id=session_id,
                actor_id=actor.id,
                expires_at=hard_expires_at,
                last_seen_at=now,
                weave_access_token_encrypted=encrypt_local_secret(
                    weave_actor.access_token.get_secret_value(),
                    purpose=LocalAuthService._weave_access_purpose(session_id),
                ),
                weave_access_token_issued_at=now,
                weave_access_token_expires_at=access_expires_at,
                weave_refresh_token_encrypted=encrypt_local_secret(
                    weave_actor.refresh_token.get_secret_value(),
                    purpose=LocalAuthService._weave_refresh_purpose(session_id),
                ),
                weave_refresh_token_expires_at=hard_expires_at,
                weave_auth_state=WEAVE_AUTH_STATE_SYNCED,
            )
            actor_session = await AuthRepository.add_session(db, actor_session)

            raw_refresh_token = generate_refresh_token()
            await AuthRepository.add_refresh_token(
                db,
                LocalRefreshToken(
                    session_id=actor_session.id,
                    token_hash=hash_refresh_token(raw_refresh_token),
                    expires_at=hard_expires_at,
                ),
            )

            access_token = LocalAuthService._issue_access_token(
                actor=actor,
                session_id=actor_session.id,
                installation_id=installation.server_id,
                expires_at=access_expires_at,
                now=now,
            )

        return LocalLoginResult(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            actor=actor,
            access_token_expires_at=access_expires_at,
            session_expires_at=hard_expires_at,
            cloud_auth_state=WEAVE_AUTH_STATE_SYNCED,
        )

    @staticmethod
    async def refresh_staff(
        db: AsyncSession,
        *,
        refresh_token: str,
        idempotency_key: UUID,
    ) -> LocalLoginResult:
        """Refresh local and Weave authorization as one coordinated operation."""

        if not refresh_token:
            raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)

        token_hash = hash_refresh_token(refresh_token)

        # Resolve the session ID before taking the distributed single-flight lock.
        async with db.begin():
            token_hint = await AuthRepository.get_refresh_token_by_hash(db, token_hash)
            if token_hint is None:
                raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)
            session_hint = await AuthRepository.get_session_by_id(
                db,
                token_hint.session_id,
            )
            if session_hint is None:
                raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)
            session_id = session_hint.id

        async with staff_refresh_lock(session_id):
            prepared = await LocalAuthService._prepare_cloud_refresh(
                db,
                token_hash=token_hash,
                local_operation_id=idempotency_key,
            )

            if isinstance(prepared, LocalLoginResult):
                return prepared

            installation = node_identity_store.load()

            try:
                token_pair = await weave_auth_gateway.refresh_staff_authorization(
                    refresh_token=prepared.cloud_refresh_token,
                    idempotency_key=prepared.cloud_operation_id,
                    server_credential=installation.server_credential,
                )
            except WeaveUnavailableError:
                return await LocalAuthService._complete_degraded_refresh(
                    db,
                    token_hash=token_hash,
                    local_operation_id=idempotency_key,
                    cloud_operation_id=prepared.cloud_operation_id,
                )
            except WeaveRequestRejectedError as exc:
                if exc.status_code in {401, 403}:
                    await LocalAuthService._revoke_session_for_cloud_rejection(
                        db,
                        token_hash=token_hash,
                    )
                    raise LocalSessionAuthenticationError(
                        INVALID_LOCAL_STAFF_SESSION
                    ) from exc

                # 429/5xx are explicitly temporary. Other non-auth cloud
                # rejections are also treated as cloud degradation rather than
                # incorrectly destroying offline local trust.
                return await LocalAuthService._complete_degraded_refresh(
                    db,
                    token_hash=token_hash,
                    local_operation_id=idempotency_key,
                    cloud_operation_id=prepared.cloud_operation_id,
                )

            return await LocalAuthService._complete_synced_refresh(
                db,
                token_hash=token_hash,
                local_operation_id=idempotency_key,
                cloud_operation_id=prepared.cloud_operation_id,
                token_pair=token_pair,
            )

    @staticmethod
    async def _prepare_cloud_refresh(
        db: AsyncSession,
        *,
        token_hash: str,
        local_operation_id: UUID,
    ) -> _PreparedCloudRefresh | LocalLoginResult:
        """Validate/lock local state and persist a cloud operation before I/O."""

        failure: str | None = None
        recovered: LocalLoginResult | None = None
        prepared: _PreparedCloudRefresh | None = None
        now = datetime.now(UTC)
        installation = node_identity_store.load()

        async with db.begin():
            actor, session, stored_token = await LocalAuthService._lock_refresh_chain(
                db,
                token_hash=token_hash,
            )

            if actor is None or session is None or stored_token is None:
                failure = INVALID_LOCAL_STAFF_SESSION
            elif (
                not actor.is_active
                or session.revoked_at is not None
                or session.expires_at <= now
            ):
                if session.revoked_at is None:
                    await LocalAuthService._revoke_session_locked(
                        db,
                        session=session,
                        now=now,
                        reason=SYNC_TRUST_REVOKED_REASON,
                    )
                failure = INVALID_LOCAL_STAFF_SESSION
            elif stored_token.revoked_at is not None or stored_token.expires_at <= now:
                if stored_token.revoked_at is None:
                    stored_token.revoked_at = now
                    await AuthRepository.save_refresh_token(db, stored_token)
                failure = INVALID_LOCAL_STAFF_SESSION
            elif stored_token.consumed_at is not None:
                recovered = await LocalAuthService._recover_local_refresh_locked(
                    db,
                    actor=actor,
                    session=session,
                    stored_token=stored_token,
                    operation_id=local_operation_id,
                    installation_id=installation.server_id,
                    now=now,
                )
                if recovered is None:
                    if stored_token.refresh_operation_id != local_operation_id:
                        if stored_token.reuse_detected_at is None:
                            stored_token.reuse_detected_at = now
                            await AuthRepository.save_refresh_token(db, stored_token)
                        await LocalAuthService._revoke_session_locked(
                            db,
                            session=session,
                            now=now,
                            reason=REFRESH_REUSE_REASON,
                        )
                    failure = INVALID_LOCAL_STAFF_SESSION
            elif (
                session.weave_auth_state == WEAVE_AUTH_STATE_LEGACY
                or session.weave_refresh_token_encrypted is None
                or session.weave_refresh_token_expires_at is None
            ):
                await LocalAuthService._revoke_session_locked(
                    db,
                    session=session,
                    now=now,
                    reason=LEGACY_SESSION_REASON,
                )
                failure = INVALID_LOCAL_STAFF_SESSION
            elif session.weave_refresh_token_expires_at <= now:
                await LocalAuthService._revoke_session_locked(
                    db,
                    session=session,
                    now=now,
                    reason=SYNC_TRUST_REVOKED_REASON,
                )
                failure = INVALID_LOCAL_STAFF_SESSION
            else:
                cloud_operation_id = (
                    session.weave_refresh_operation_id or local_operation_id
                )
                session.weave_refresh_operation_id = cloud_operation_id
                session.weave_auth_state = WEAVE_AUTH_STATE_REFRESH_PENDING
                await AuthRepository.save_session(db, session)

                try:
                    cloud_refresh_token = decrypt_local_secret(
                        session.weave_refresh_token_encrypted,
                        purpose=LocalAuthService._weave_refresh_purpose(session.id),
                    )
                except StoredSecretDecryptionError:
                    await LocalAuthService._revoke_session_locked(
                        db,
                        session=session,
                        now=now,
                        reason=SYNC_TRUST_REVOKED_REASON,
                    )
                    failure = INVALID_LOCAL_STAFF_SESSION
                else:
                    prepared = _PreparedCloudRefresh(
                        session_id=session.id,
                        cloud_operation_id=cloud_operation_id,
                        cloud_refresh_token=cloud_refresh_token,
                    )

        if failure is not None:
            raise LocalSessionAuthenticationError(failure)
        if recovered is not None:
            return recovered
        if prepared is None:
            raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)
        return prepared

    @staticmethod
    async def _complete_synced_refresh(
        db: AsyncSession,
        *,
        token_hash: str,
        local_operation_id: UUID,
        cloud_operation_id: UUID,
        token_pair: WeaveActorTokenPair,
    ) -> LocalLoginResult:
        now = datetime.now(UTC)
        access_expires_at, refresh_expires_at = (
            LocalAuthService._validate_token_pair_times(
                access_expires_at=token_pair.access_token_expires_at,
                refresh_expires_at=token_pair.refresh_token_expires_at,
                now=now,
            )
        )
        installation = node_identity_store.load()
        failure: str | None = None
        result: LocalLoginResult | None = None

        async with db.begin():
            actor, session, stored_token = await LocalAuthService._lock_refresh_chain(
                db,
                token_hash=token_hash,
            )
            if (
                actor is None
                or session is None
                or stored_token is None
                or (
                    session.revoked_at is not None
                    or not actor.is_active
                    or session.expires_at <= now
                    or stored_token.consumed_at is not None
                    or stored_token.revoked_at is not None
                )
                or session.weave_refresh_operation_id != cloud_operation_id
            ):
                failure = INVALID_LOCAL_STAFF_SESSION
            elif refresh_expires_at > session.expires_at + timedelta(seconds=2):
                raise WeaveContractError(
                    "Weave attempted to extend the absolute CBT staff authorization lifetime."
                )
            else:
                session.expires_at = min(session.expires_at, refresh_expires_at)

                session.weave_access_token_encrypted = encrypt_local_secret(
                    token_pair.access_token.get_secret_value(),
                    purpose=LocalAuthService._weave_access_purpose(session.id),
                )
                session.weave_access_token_issued_at = now
                session.weave_access_token_expires_at = min(
                    access_expires_at,
                    session.expires_at,
                )
                session.weave_refresh_token_encrypted = encrypt_local_secret(
                    token_pair.refresh_token.get_secret_value(),
                    purpose=LocalAuthService._weave_refresh_purpose(session.id),
                )
                session.weave_refresh_token_expires_at = min(
                    refresh_expires_at,
                    session.expires_at,
                )
                session.weave_refresh_operation_id = None
                session.weave_auth_state = WEAVE_AUTH_STATE_SYNCED
                actor.last_weave_revalidated_at = now
                await AuthRepository.save_actor(db, actor)

                result = await LocalAuthService._rotate_local_refresh_locked(
                    db,
                    actor=actor,
                    session=session,
                    stored_token=stored_token,
                    operation_id=local_operation_id,
                    installation_id=installation.server_id,
                    access_expires_at=session.weave_access_token_expires_at,
                    now=now,
                )

        if failure is not None:
            raise LocalSessionAuthenticationError(failure)
        if result is None:
            raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)
        return result

    @staticmethod
    async def _complete_degraded_refresh(
        db: AsyncSession,
        *,
        token_hash: str,
        local_operation_id: UUID,
        cloud_operation_id: UUID,
    ) -> LocalLoginResult:
        """Keep local CBT usable while preserving the unresolved cloud operation."""

        now = datetime.now(UTC)
        installation = node_identity_store.load()
        failure: str | None = None
        result: LocalLoginResult | None = None

        async with db.begin():
            actor, session, stored_token = await LocalAuthService._lock_refresh_chain(
                db,
                token_hash=token_hash,
            )
            if (
                actor is None
                or session is None
                or stored_token is None
                or (
                    not actor.is_active
                    or session.revoked_at is not None
                    or session.expires_at <= now
                    or stored_token.consumed_at is not None
                    or stored_token.revoked_at is not None
                )
            ):
                failure = INVALID_LOCAL_STAFF_SESSION
            else:
                # Keep the same pending cloud operation ID. The next refresh will
                # retry the exact same Weave operation and can recover a response
                # that was committed but lost on the network.
                session.weave_refresh_operation_id = cloud_operation_id
                session.weave_auth_state = WEAVE_AUTH_STATE_DEGRADED
                degraded_expiry = LocalAuthService._degraded_access_expiry(
                    session=session,
                    now=now,
                )
                result = await LocalAuthService._rotate_local_refresh_locked(
                    db,
                    actor=actor,
                    session=session,
                    stored_token=stored_token,
                    operation_id=local_operation_id,
                    installation_id=installation.server_id,
                    access_expires_at=degraded_expiry,
                    now=now,
                )

        if failure is not None:
            raise LocalSessionAuthenticationError(failure)
        if result is None:
            raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)
        return result

    @staticmethod
    async def _recover_local_refresh_locked(
        db: AsyncSession,
        *,
        actor: LocalActor,
        session: LocalActorSession,
        stored_token: LocalRefreshToken,
        operation_id: UUID,
        installation_id: UUID,
        now: datetime,
    ) -> LocalLoginResult | None:
        """Recover the exact local replacement token for a repeated operation."""

        if (
            stored_token.refresh_operation_id != operation_id
            or stored_token.replacement_token_encrypted is None
            or stored_token.replaced_by_token_id is None
        ):
            return None

        replacement = await AuthRepository.get_refresh_token_by_id(
            db,
            stored_token.replaced_by_token_id,
            lock=True,
        )
        if (
            replacement is None
            or replacement.session_id != session.id
            or replacement.revoked_at is not None
            or replacement.consumed_at is not None
            or replacement.expires_at <= now
        ):
            return None

        try:
            raw_replacement = decrypt_local_secret(
                stored_token.replacement_token_encrypted,
                purpose=LocalAuthService._local_refresh_recovery_purpose(
                    stored_token.id,
                    operation_id,
                ),
            )
        except StoredSecretDecryptionError:
            return None

        access_expires_at = LocalAuthService._current_local_access_expiry(
            session=session,
            now=now,
        )
        session.last_seen_at = now
        await AuthRepository.save_session(db, session)
        return LocalLoginResult(
            access_token=LocalAuthService._issue_access_token(
                actor=actor,
                session_id=session.id,
                installation_id=installation_id,
                expires_at=access_expires_at,
                now=now,
            ),
            refresh_token=raw_replacement,
            actor=actor,
            access_token_expires_at=access_expires_at,
            session_expires_at=session.expires_at,
            cloud_auth_state=session.weave_auth_state,
        )

    @staticmethod
    async def _rotate_local_refresh_locked(
        db: AsyncSession,
        *,
        actor: LocalActor,
        session: LocalActorSession,
        stored_token: LocalRefreshToken,
        operation_id: UUID,
        installation_id: UUID,
        access_expires_at: datetime,
        now: datetime,
    ) -> LocalLoginResult:
        replacement_raw_token = generate_refresh_token()
        replacement = await AuthRepository.add_refresh_token(
            db,
            LocalRefreshToken(
                session_id=session.id,
                token_hash=hash_refresh_token(replacement_raw_token),
                expires_at=session.expires_at,
            ),
        )

        stored_token.consumed_at = now
        stored_token.replaced_by_token_id = replacement.id
        stored_token.refresh_operation_id = operation_id
        stored_token.replacement_token_encrypted = encrypt_local_secret(
            replacement_raw_token,
            purpose=LocalAuthService._local_refresh_recovery_purpose(
                stored_token.id,
                operation_id,
            ),
        )
        await AuthRepository.save_refresh_token(db, stored_token)

        session.last_refreshed_at = now
        session.last_seen_at = now
        await AuthRepository.save_session(db, session)

        access_expires_at = min(access_expires_at, session.expires_at)
        if access_expires_at <= now:
            raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)

        return LocalLoginResult(
            access_token=LocalAuthService._issue_access_token(
                actor=actor,
                session_id=session.id,
                installation_id=installation_id,
                expires_at=access_expires_at,
                now=now,
            ),
            refresh_token=replacement_raw_token,
            actor=actor,
            access_token_expires_at=access_expires_at,
            session_expires_at=session.expires_at,
            cloud_auth_state=session.weave_auth_state,
        )

    @staticmethod
    async def _revoke_session_for_cloud_rejection(
        db: AsyncSession,
        *,
        token_hash: str,
    ) -> None:
        now = datetime.now(UTC)
        async with db.begin():
            _, session, _ = await LocalAuthService._lock_refresh_chain(
                db,
                token_hash=token_hash,
            )
            if session is not None:
                await LocalAuthService._revoke_session_locked(
                    db,
                    session=session,
                    now=now,
                    reason=WEAVE_AUTH_REJECTED_REASON,
                )

    @staticmethod
    async def logout_staff(
        db: AsyncSession,
        *,
        refresh_token: str | None,
    ) -> None:
        """Revoke the local staff session represented by a refresh token."""

        if not refresh_token:
            return
        try:
            token_hash = hash_refresh_token(refresh_token)
        except ValueError:
            return

        now = datetime.now(UTC)
        async with db.begin():
            token_hint = await AuthRepository.get_refresh_token_by_hash(db, token_hash)
            if token_hint is None:
                return
            session_hint = await AuthRepository.get_session_by_id(
                db, token_hint.session_id
            )
            if session_hint is None:
                return
            actor = await AuthRepository.get_actor_by_id(
                db,
                session_hint.actor_id,
                lock=True,
            )
            session = await AuthRepository.get_session_by_id(
                db,
                session_hint.id,
                lock=True,
            )
            stored_token = await AuthRepository.get_refresh_token_by_hash(
                db,
                token_hash,
                lock=True,
            )
            if (
                session is None
                or stored_token is None
                or stored_token.session_id != session.id
                or (actor is not None and session.actor_id != actor.id)
            ):
                return
            await LocalAuthService._revoke_session_locked(
                db,
                session=session,
                now=now,
                reason=LOGOUT_REASON,
            )

    @staticmethod
    async def get_weave_actor_access_token(
        db: AsyncSession,
        *,
        session_id: UUID,
    ) -> str:
        """Return the current usable Weave actor access token for cloud calls."""

        session = await AuthRepository.get_session_by_id(db, session_id)
        now = datetime.now(UTC)
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= now
            or session.weave_auth_state != WEAVE_AUTH_STATE_SYNCED
            or session.weave_access_token_encrypted is None
            or session.weave_access_token_expires_at is None
            or session.weave_access_token_expires_at <= now
        ):
            raise LocalSessionAuthenticationError(
                "Weave cloud authorization requires refresh."
            )
        try:
            return decrypt_local_secret(
                session.weave_access_token_encrypted,
                purpose=LocalAuthService._weave_access_purpose(session.id),
            )
        except StoredSecretDecryptionError as exc:
            raise LocalSessionAuthenticationError(
                "Weave cloud authorization is unavailable."
            ) from exc

    @staticmethod
    async def reconcile_synced_staff_trust(
        db: AsyncSession,
        *,
        revalidated_at: datetime | None = None,
    ) -> None:
        """Remove local trust when the authoritative staff projection disappears."""

        checked_at = revalidated_at or datetime.now(UTC)
        actor_hints = await AuthRepository.list_actors(db, active_only=True)

        for actor_hint in actor_hints:
            actor = await AuthRepository.get_actor_by_id(
                db,
                actor_hint.id,
                lock=True,
            )
            if actor is None or not actor.is_active:
                continue

            trusted = await LocalAuthService._projection_trusts_actor(db, actor=actor)
            actor.last_weave_revalidated_at = checked_at
            if trusted:
                await AuthRepository.save_actor(db, actor)
                continue

            actor.is_active = False
            await AuthRepository.save_actor(db, actor)
            sessions = await AuthRepository.list_sessions_for_actor(
                db,
                actor.id,
                include_revoked=False,
                lock=True,
            )
            for session in sessions:
                await LocalAuthService._revoke_session_locked(
                    db,
                    session=session,
                    now=checked_at,
                    reason=SYNC_TRUST_REVOKED_REASON,
                )

    @staticmethod
    async def _projection_trusts_actor(
        db: AsyncSession,
        *,
        actor: LocalActor,
    ) -> bool:
        if actor.role == "admin":
            try:
                admin_id = UUID(actor.weave_actor_id)
            except (TypeError, ValueError):
                return False
            admin = await AcademicRepository.get_admin_by_id(db, admin_id)
            return admin is not None and str(admin.status).lower() == "active"

        if actor.role == "teacher":
            if actor.weave_membership_id is None:
                return False
            try:
                membership_id = UUID(actor.weave_membership_id)
            except (TypeError, ValueError):
                return False
            teacher = await AcademicRepository.get_teacher_by_membership_id(
                db,
                membership_id,
            )
            return bool(
                teacher is not None
                and str(teacher.status).lower() == "active"
                and str(teacher.teacher_account_id) == actor.weave_actor_id
            )
        return False

    @staticmethod
    async def _lock_refresh_chain(
        db: AsyncSession,
        *,
        token_hash: str,
    ) -> tuple[LocalActor | None, LocalActorSession | None, LocalRefreshToken | None]:
        token_hint = await AuthRepository.get_refresh_token_by_hash(db, token_hash)
        if token_hint is None:
            return None, None, None
        session_hint = await AuthRepository.get_session_by_id(db, token_hint.session_id)
        if session_hint is None:
            return None, None, None

        actor = await AuthRepository.get_actor_by_id(
            db,
            session_hint.actor_id,
            lock=True,
        )
        session = await AuthRepository.get_session_by_id(
            db,
            session_hint.id,
            lock=True,
        )
        stored_token = await AuthRepository.get_refresh_token_by_hash(
            db,
            token_hash,
            lock=True,
        )
        if (
            actor is None
            or session is None
            or stored_token is None
            or stored_token.session_id != session.id
            or session.actor_id != actor.id
        ):
            return None, None, None
        return actor, session, stored_token

    @staticmethod
    async def _revoke_session_locked(
        db: AsyncSession,
        *,
        session: LocalActorSession,
        now: datetime,
        reason: str,
    ) -> None:
        if session.revoked_at is None:
            session.revoked_at = now
            session.revocation_reason = reason
        session.weave_auth_state = WEAVE_AUTH_STATE_REVOKED
        session.weave_access_token_encrypted = None
        session.weave_refresh_token_encrypted = None
        session.weave_refresh_operation_id = None
        await AuthRepository.save_session(db, session)

        refresh_tokens = await AuthRepository.list_refresh_tokens_for_session(
            db,
            session.id,
            include_revoked=False,
            lock=True,
        )
        changed: list[LocalRefreshToken] = []
        for token in refresh_tokens:
            if token.revoked_at is None:
                token.revoked_at = now
                token.replacement_token_encrypted = None
                changed.append(token)
        if changed:
            await AuthRepository.save_refresh_tokens(db, changed)

    @staticmethod
    def _issue_access_token(
        *,
        actor: LocalActor,
        session_id: UUID,
        installation_id: UUID,
        expires_at: datetime,
        now: datetime,
    ) -> str:
        additional_claims: dict[str, str] = {}
        if actor.weave_membership_id is not None:
            additional_claims["membership_id"] = actor.weave_membership_id

        return create_local_access_token(
            subject=actor.weave_actor_id,
            session_id=str(session_id),
            role=actor.role,
            installation_id=str(installation_id),
            expires_at=expires_at,
            additional_claims=additional_claims,
            now=now,
        )

    @staticmethod
    def _current_local_access_expiry(
        *,
        session: LocalActorSession,
        now: datetime,
    ) -> datetime:
        if (
            session.weave_auth_state == WEAVE_AUTH_STATE_SYNCED
            and session.weave_access_token_expires_at is not None
            and session.weave_access_token_expires_at > now
        ):
            return min(session.weave_access_token_expires_at, session.expires_at)
        return LocalAuthService._degraded_access_expiry(session=session, now=now)

    @staticmethod
    def _degraded_access_expiry(
        *,
        session: LocalActorSession,
        now: datetime,
    ) -> datetime:
        issued_at = session.weave_access_token_issued_at
        expires_at = session.weave_access_token_expires_at
        if issued_at is None or expires_at is None or expires_at <= issued_at:
            raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)

        observed_window = expires_at - issued_at
        window = max(
            MIN_DEGRADED_ACCESS_WINDOW,
            min(observed_window, MAX_DEGRADED_ACCESS_WINDOW),
        )
        degraded_expiry = min(now + window, session.expires_at)
        if degraded_expiry <= now:
            raise LocalSessionAuthenticationError(INVALID_LOCAL_STAFF_SESSION)
        return degraded_expiry

    @staticmethod
    def _validate_weave_identity(
        *,
        weave_actor: WeaveStaffAuthResult,
        tenant_id: UUID,
    ) -> None:
        if weave_actor.tenant_id != tenant_id:
            raise WeaveContractError(
                "Weave returned staff identity for an unexpected tenant"
            )
        if weave_actor.role == "teacher" and weave_actor.membership_id is None:
            raise WeaveContractError("Weave returned a teacher without a membership")
        if weave_actor.role == "admin" and weave_actor.membership_id is not None:
            raise WeaveContractError(
                "Weave returned an unexpected membership for an administrator"
            )

    @staticmethod
    def _validate_token_pair_times(
        *,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
        now: datetime,
    ) -> tuple[datetime, datetime]:
        if access_expires_at.tzinfo is None or refresh_expires_at.tzinfo is None:
            raise WeaveContractError("Weave returned naive authorization timestamps.")
        access_expiry = access_expires_at.astimezone(UTC)
        refresh_expiry = refresh_expires_at.astimezone(UTC)
        if access_expiry <= now or refresh_expiry <= now:
            raise WeaveContractError(
                "Weave returned already-expired authorization tokens."
            )
        if access_expiry > refresh_expiry:
            raise WeaveContractError(
                "Weave access-token expiry exceeds the authorization hard expiry."
            )
        return access_expiry, refresh_expiry

    @staticmethod
    def _weave_access_purpose(session_id: UUID) -> str:
        return f"auth:session:{session_id}:weave-access"

    @staticmethod
    def _weave_refresh_purpose(session_id: UUID) -> str:
        return f"auth:session:{session_id}:weave-refresh"

    @staticmethod
    def _local_refresh_recovery_purpose(token_id: UUID, operation_id: UUID) -> str:
        return f"auth:local-refresh:{token_id}:operation:{operation_id}"

    @staticmethod
    async def _upsert_actor(
        db: AsyncSession,
        *,
        weave_actor: WeaveStaffAuthResult,
        now: datetime,
    ) -> LocalActor:
        weave_actor_id = str(weave_actor.actor_id)
        weave_membership_id = (
            str(weave_actor.membership_id)
            if weave_actor.membership_id is not None
            else None
        )
        display_name = LocalAuthService._build_display_name(
            first_name=weave_actor.first_name,
            last_name=weave_actor.last_name,
            email=str(weave_actor.email),
        )

        actor = await AuthRepository.get_actor_by_weave_identity(
            db,
            weave_actor_id,
            weave_actor.role,
            lock=True,
        )
        if actor is None:
            return await AuthRepository.add_actor(
                db,
                LocalActor(
                    weave_actor_id=weave_actor_id,
                    weave_membership_id=weave_membership_id,
                    role=weave_actor.role,
                    email=str(weave_actor.email),
                    display_name=display_name,
                    is_active=True,
                    last_weave_authenticated_at=now,
                    last_weave_revalidated_at=now,
                ),
            )

        actor.weave_membership_id = weave_membership_id
        actor.email = str(weave_actor.email)
        actor.display_name = display_name
        actor.is_active = True
        actor.last_weave_authenticated_at = now
        actor.last_weave_revalidated_at = now
        return await AuthRepository.save_actor(db, actor)

    @staticmethod
    def _build_display_name(
        *,
        first_name: str | None,
        last_name: str | None,
        email: str,
    ) -> str:
        parts = [
            value.strip()
            for value in (first_name, last_name)
            if value and value.strip()
        ]
        return " ".join(parts) if parts else email
