import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { RiRefreshLine } from '@remixicon/react'
import { Notice } from '../../../shared/ui'
import '../admin-roster-actions.css'

const READ_ONLY_EXAM_STATES = new Set(['closing', 'cancelling', 'closed', 'cancelled'])

export function RosterCandidateActionButton({ candidate, exam, gateway, onChanged }) {
  const [dialog, setDialog] = useState(null)
  const [authorizationClock, setAuthorizationClock] = useState(() => Date.now())
  const [authorizations, setAuthorizations] = useState([])
  const [loadingAuthorizations, setLoadingAuthorizations] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [blockReason, setBlockReason] = useState('')
  const [lateStartReason, setLateStartReason] = useState('')
  const [lateStartExpiry, setLateStartExpiry] = useState('')
  const [revocationReason, setRevocationReason] = useState('')
  const [attemptReason, setAttemptReason] = useState('')

  const readOnlyExam = READ_ONLY_EXAM_STATES.has(exam.status)
  const attemptStatus = candidate.attempt?.status || null
  const hasAttempt = Boolean(candidate.attempt)
  const canChangeEligibility = !readOnlyExam && !hasAttempt && candidate.status !== 'withdrawn'
  const canGrantLateStart = Boolean(
    !readOnlyExam
    && !hasAttempt
    && exam.status === 'active'
    && candidate.status === 'eligible'
    && (candidate.late_start_required || candidate.late_start_authorized),
  )
  const canInterrupt = !readOnlyExam && exam.status === 'active' && attemptStatus === 'in_progress'
  const canResume = !readOnlyExam && exam.status === 'active' && attemptStatus === 'interrupted'

  const activeAuthorization = useMemo(() => {
    const now = authorizationClock
    return [...authorizations]
      .sort((a, b) => new Date(b.granted_at).getTime() - new Date(a.granted_at).getTime())
      .find((authorization) => {
        if (authorization.revoked_at || authorization.consumed_at) return false
        if (!authorization.expires_at) return true
        return new Date(authorization.expires_at).getTime() > now
      }) || null
  }, [authorizations, authorizationClock])

  const loadAuthorizations = useCallback(async () => {
    setLoadingAuthorizations(true)
    setError('')
    try {
      const response = await gateway.candidates.listLateStartAuthorizations(candidate.id)
      setAuthorizations(Array.isArray(response) ? response : [])
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not load late-start authorization details.')
    } finally {
      setLoadingAuthorizations(false)
    }
  }, [candidate.id, gateway])

  useEffect(() => {
    if (!dialog) return undefined
    if (dialog !== 'late-start') return undefined
    const timer = window.setInterval(() => setAuthorizationClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [dialog])

  useEffect(() => {
    if (!dialog) return undefined

    const closeOnEscape = (event) => {
      if (event.key === 'Escape' && !busy) setDialog(null)
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [busy, dialog])

  const closeDialog = () => {
    if (busy) return
    setDialog(null)
    setError('')
    setBlockReason('')
    setLateStartReason('')
    setLateStartExpiry('')
    setRevocationReason('')
    setAttemptReason('')
  }

  const blockCandidate = async () => {
    const reason = blockReason.trim()
    if (!reason) {
      setError('Enter a reason before blocking this candidate.')
      return
    }
    setBusy('block')
    setError('')
    try {
      await gateway.candidates.blockCandidate(candidate.id, reason)
      await onChanged?.()
      closeDialogAfterMutation(setDialog, setBlockReason)
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not block this candidate.')
    } finally {
      setBusy('')
    }
  }

  const unblockCandidate = async () => {
    setBusy('unblock')
    setError('')
    try {
      await gateway.candidates.unblockCandidate(candidate.id)
      await onChanged?.()
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not unblock this candidate.')
    } finally {
      setBusy('')
    }
  }

  const grantLateStart = async () => {
    const reason = lateStartReason.trim()
    if (!reason) {
      setError('Enter a reason before granting late-start access.')
      return
    }

    let expiresAt = null
    if (lateStartExpiry) {
      const parsed = new Date(lateStartExpiry)
      if (Number.isNaN(parsed.getTime())) {
        setError('Enter a valid expiry date and time.')
        return
      }
      expiresAt = parsed.toISOString()
    }

    setBusy('grant-late-start')
    setError('')
    try {
      await gateway.candidates.grantLateStart(candidate.id, {
        reason,
        expires_at: expiresAt,
      })
      setLateStartReason('')
      setLateStartExpiry('')
      await onChanged?.()
      await loadAuthorizations()
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not grant late-start access.')
    } finally {
      setBusy('')
    }
  }

  const revokeLateStart = async () => {
    if (!activeAuthorization) return
    const reason = revocationReason.trim()
    if (!reason) {
      setError('Enter a reason before revoking late-start access.')
      return
    }
    setBusy('revoke-late-start')
    setError('')
    try {
      await gateway.candidates.revokeLateStart(activeAuthorization.id, reason)
      setRevocationReason('')
      await onChanged?.()
      await loadAuthorizations()
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not revoke late-start access.')
    } finally {
      setBusy('')
    }
  }

  const mutateAttempt = async (action) => {
    const reason = attemptReason.trim()
    if (!reason) {
      setError(`Enter a reason before ${action === 'interrupt' ? 'interrupting' : 'resuming'} this attempt.`)
      return
    }
    setBusy(action)
    setError('')
    try {
      if (action === 'interrupt') await gateway.attempts.interruptAttempt(candidate.attempt.id, reason)
      else await gateway.attempts.resumeAttempt(candidate.attempt.id, reason)
      await onChanged?.()
      closeDialogAfterMutation(setDialog, setAttemptReason)
    } catch (requestError) {
      setError(requestError.userMessage || `Weave could not ${action} this attempt.`)
    } finally {
      setBusy('')
    }
  }

  const showBlock = candidate.status === 'eligible' && canChangeEligibility
  const showUnblock = candidate.status === 'blocked' && canChangeEligibility
  const noActions = readOnlyExam || candidate.status === 'withdrawn' || (!showBlock && !showUnblock && !canGrantLateStart && !canInterrupt && !canResume)

  return (
    <>
      <div className="admin-roster-row-actions">
        {showBlock && (
          <button className="admin-roster-row-action admin-roster-row-action--danger" type="button" disabled={Boolean(busy)} onClick={() => { setError(''); setDialog('block') }}>
            Block
          </button>
        )}

        {showUnblock && (
          <button className="admin-roster-row-action admin-roster-row-action--primary" type="button" disabled={Boolean(busy)} onClick={() => void unblockCandidate()}>
            {busy === 'unblock' ? 'Unblocking…' : 'Unblock'}
          </button>
        )}

        {canGrantLateStart && (
          <button className="admin-roster-row-action admin-roster-row-action--secondary" type="button" disabled={Boolean(busy)} onClick={() => { setError(''); setAuthorizationClock(Date.now()); setDialog('late-start'); void loadAuthorizations() }}>
            {candidate.late_start_authorized ? 'Late start granted' : 'Late start'}
          </button>
        )}

        {canInterrupt && (
          <button className="admin-roster-row-action admin-roster-row-action--danger" type="button" disabled={Boolean(busy)} onClick={() => { setError(''); setDialog('interrupt') }}>
            Interrupt
          </button>
        )}

        {canResume && (
          <button className="admin-roster-row-action admin-roster-row-action--primary" type="button" disabled={Boolean(busy)} onClick={() => { setError(''); setDialog('resume') }}>
            Resume
          </button>
        )}

        {noActions && <span className="admin-roster-row-actions__empty">—</span>}
        {error && !dialog && <span className="admin-roster-row-actions__error" title={error}>Action failed</span>}
      </div>

      {dialog === 'block' && (
        <ActionDialog title="Block candidate" candidate={candidate} busy={Boolean(busy)} onClose={closeDialog}>
          <p className="admin-roster-dialog-copy">This prevents <strong>{candidate.display_name}</strong> from starting this examination. It does not change the student’s enrollment in Weave.</p>
          {error && <Notice tone="danger">{error}</Notice>}
          <label className="admin-roster-dialog-field"><span>Reason for blocking</span><textarea autoFocus value={blockReason} onChange={(event) => setBlockReason(event.target.value)} placeholder="e.g. Candidate is not cleared to sit this examination." maxLength={500} /></label>
          <div className="admin-roster-dialog-footer">
            <button className="admin-roster-dialog-button admin-roster-dialog-button--secondary" type="button" disabled={Boolean(busy)} onClick={closeDialog}>Cancel</button>
            <button className="admin-roster-dialog-button admin-roster-dialog-button--danger" type="button" disabled={Boolean(busy)} onClick={() => void blockCandidate()}>{busy === 'block' ? 'Blocking…' : 'Block candidate'}</button>
          </div>
        </ActionDialog>
      )}

      {dialog === 'late-start' && (
        <ActionDialog title="Late-start authorization" candidate={candidate} busy={Boolean(busy)} onClose={closeDialog}>
          <p className="admin-roster-dialog-copy">Allow this eligible candidate to begin after the normal entry window for the active examination.</p>
          {error && <Notice tone="danger">{error}</Notice>}
          {loadingAuthorizations && <div className="admin-roster-dialog-loading">Loading authorization status…</div>}
          {!loadingAuthorizations && activeAuthorization && (
            <div className="admin-roster-authorization-card">
              <div className="admin-roster-authorization-card__header"><strong>Late start is active</strong><span>{activeAuthorization.expires_at ? `Expires ${formatActionDate(activeAuthorization.expires_at)}` : 'No expiry'}</span></div>
              <p>{activeAuthorization.reason}</p>
              <label className="admin-roster-dialog-field"><span>Reason for revocation</span><textarea value={revocationReason} onChange={(event) => setRevocationReason(event.target.value)} placeholder="Why should this authorization be revoked?" /></label>
              <div className="admin-roster-dialog-footer">
                <button className="admin-roster-dialog-button admin-roster-dialog-button--secondary" type="button" disabled={Boolean(busy)} onClick={closeDialog}>Close</button>
                <button className="admin-roster-dialog-button admin-roster-dialog-button--danger-outline" type="button" disabled={Boolean(busy)} onClick={() => void revokeLateStart()}>{busy === 'revoke-late-start' ? 'Revoking…' : 'Revoke access'}</button>
              </div>
            </div>
          )}
          {!loadingAuthorizations && !activeAuthorization && (
            <>
              <label className="admin-roster-dialog-field"><span>Reason</span><textarea autoFocus value={lateStartReason} onChange={(event) => setLateStartReason(event.target.value)} placeholder="State why this candidate is being allowed to start late." /></label>
              <label className="admin-roster-dialog-field"><span>Expires at <small>(optional)</small></span><input type="datetime-local" value={lateStartExpiry} onChange={(event) => setLateStartExpiry(event.target.value)} /></label>
              <div className="admin-roster-dialog-footer">
                <button className="admin-roster-dialog-button admin-roster-dialog-button--secondary" type="button" disabled={Boolean(busy)} onClick={closeDialog}>Cancel</button>
                <button className="admin-roster-dialog-button admin-roster-dialog-button--primary" type="button" disabled={Boolean(busy)} onClick={() => void grantLateStart()}>{busy === 'grant-late-start' ? 'Granting…' : 'Grant late start'}</button>
              </div>
            </>
          )}
        </ActionDialog>
      )}

      {(dialog === 'interrupt' || dialog === 'resume') && (
        <ActionDialog title={dialog === 'interrupt' ? 'Interrupt attempt' : 'Resume attempt'} candidate={candidate} busy={Boolean(busy)} onClose={closeDialog}>
          <p className="admin-roster-dialog-copy">
            {dialog === 'interrupt'
              ? `Pause ${candidate.display_name}'s active attempt. Their saved answers remain safe and their timer stops until the attempt is resumed.`
              : `Resume ${candidate.display_name}'s interrupted attempt and continue their remaining writing time.`}
          </p>
          {error && <Notice tone="danger">{error}</Notice>}
          <label className="admin-roster-dialog-field">
            <span>Reason</span>
            <textarea autoFocus value={attemptReason} onChange={(event) => setAttemptReason(event.target.value)} maxLength={500} placeholder={dialog === 'interrupt' ? 'Why is this attempt being paused?' : 'Why is this attempt being resumed?'} />
          </label>
          <div className="admin-roster-dialog-footer">
            <button className="admin-roster-dialog-button admin-roster-dialog-button--secondary" type="button" disabled={Boolean(busy)} onClick={closeDialog}>Cancel</button>
            <button className={`admin-roster-dialog-button ${dialog === 'interrupt' ? 'admin-roster-dialog-button--danger' : 'admin-roster-dialog-button--primary'}`} type="button" disabled={Boolean(busy)} onClick={() => void mutateAttempt(dialog)}>
              {busy ? `${dialog === 'interrupt' ? 'Interrupting' : 'Resuming'}…` : dialog === 'interrupt' ? 'Interrupt attempt' : 'Resume attempt'}
            </button>
          </div>
        </ActionDialog>
      )}
    </>
  )
}

function ActionDialog({ title, candidate, busy, onClose, children }) {
  return createPortal(
    <div className="admin-roster-action-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}>
      <section className="admin-roster-action-dialog" role="dialog" aria-modal="true" aria-labelledby={`candidate-action-${candidate.id}`}>
        <header className="admin-roster-action-dialog__header"><div><span>Candidate action</span><h2 id={`candidate-action-${candidate.id}`}>{title}</h2><p>{candidate.display_name} · {candidate.admission_number}{candidate.class_name ? ` · ${candidate.class_name}` : ''}</p></div><button type="button" aria-label="Close dialog" disabled={busy} onClick={onClose}>×</button></header>
        <div className="admin-roster-action-dialog__body">{children}</div>
      </section>
    </div>,
    document.body,
  )
}

function closeDialogAfterMutation(setDialog, resetField) {
  resetField('')
  setDialog(null)
}

export function RosterRecoveryNotice({ exam, onRefresh, onRetry, onOpenOperations }) {
  const [checking, setChecking] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [error, setError] = useState('')
  if (!['stale', 'failed'].includes(exam.rosterStatus)) return null

  const refresh = async () => {
    setChecking(true); setError('')
    try { await onRefresh?.() } catch (requestError) { setError(requestError.userMessage || 'Weave could not refresh the roster status.') } finally { setChecking(false) }
  }
  const retry = async () => {
    setRetrying(true); setError('')
    try { await onRetry?.() } catch (requestError) { setError(requestError.userMessage || 'Weave could not retry roster recovery.') } finally { setRetrying(false) }
  }
  const failed = exam.rosterStatus === 'failed'
  const busy = checking || retrying

  return (
    <div className={`admin-roster-recovery admin-roster-recovery--${failed ? 'failed' : 'stale'}`} role={failed ? 'alert' : 'status'}>
      <div className="admin-roster-recovery__copy"><strong>{failed ? 'Roster recovery needs attention' : 'Roster refresh in progress'}</strong><p>{failed ? (exam.rosterError || 'The last roster preparation or reconciliation attempt failed. Review the failure and retry when the underlying issue is resolved.') : 'Enrollment changed in Weave. The maintenance worker will reconcile this sealed roster automatically before activation.'}</p>{error && <small>{error}</small>}</div>
      <div className="admin-roster-recovery__actions">
        {failed && <button type="button" disabled={busy} onClick={retry}><RiRefreshLine size={16} /> {retrying ? 'Retrying…' : 'Retry roster'}</button>}
        <button type="button" className={failed ? 'admin-roster-recovery__secondary' : ''} disabled={busy} onClick={refresh}><RiRefreshLine size={16} /> {checking ? 'Checking…' : 'Refresh status'}</button>
        {failed && <button type="button" className="admin-roster-recovery__secondary" disabled={busy} onClick={onOpenOperations}>Open Exam Operations</button>}
      </div>
    </div>
  )
}

function formatActionDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}
