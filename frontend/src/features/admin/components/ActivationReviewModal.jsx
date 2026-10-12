import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '../../../shared/icons/Icon'

// Recovery guidance must remain inside the dialog, visible alongside the times.
function Notice({ tone, children }) {
  return <div className={`admin-ops-activation-notice is-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>{children}</div>
}

const BLOCKER_COPY = {
  too_early: 'This examination has not reached its scheduled start time.',
  schedule_date_expired: 'This examination was scheduled for a previous date. Its own schedule must be updated before activation.',
  candidate_scope_conflict: 'Candidates are already assigned to an active, suspended, or finalizing examination. Resolve that sitting first; shifting later exams will not release them.',
  missing_delivery_scope: 'This examination has no delivery scope. Review its candidate roster before activation.',
  missing_schedule: 'This examination needs a scheduled start time before activation.',
}

function displayTime(value) {
  return value ? new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' }) : 'Not available'
}

// datetime-local uses the browser's local timezone; requests carry explicit UTC.
function localInput(value) {
  if (!value) return ''
  // Round up, so dropping server microseconds never moves a suggestion earlier
  // than the safe boundary calculated by the backend.
  const date = new Date(Math.ceil(new Date(value).getTime() / 1000) * 1000)
  const adjusted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return adjusted.toISOString().slice(0, 19)
}

function suggestedTimes(preflight) {
  return Object.fromEntries(preflight.affected_exams.map((impact) => [impact.exam_id, localInput(impact.suggested_start_at)]))
}

export function ActivationReviewModal({ exam, exams, gateway, onCancel, onRefresh, onActivated }) {
  const [preflight, setPreflight] = useState(null)
  const [times, setTimes] = useState({})
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState('checking')
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const dialogRef = useRef(null)
  const busyRef = useRef(busy)
  const cancelRef = useRef(onCancel)
  useEffect(() => {
    busyRef.current = busy
    cancelRef.current = onCancel
  }, [busy, onCancel])

  const acceptPreflight = (result) => {
    setPreflight(result)
    setTimes(suggestedTimes(result))
    setNow(Date.now())
  }

  useEffect(() => {
    let mounted = true
    gateway.exams.activationPreflight(exam.id).then((result) => {
      if (mounted) {
        setPreflight(result)
        setTimes(suggestedTimes(result))
      }
    }).catch((requestError) => {
      if (mounted) setError(requestError.userMessage || 'Could not check the activation timetable. Try again.')
    }).finally(() => { if (mounted) setBusy('') })
    return () => { mounted = false }
  }, [exam.id, gateway])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const previousFocus = document.activeElement
    dialogRef.current?.focus()
    const handleKey = (event) => {
      if (event.key === 'Escape' && !busyRef.current) cancelRef.current()
      if (event.key !== 'Tab') return
      const elements = [...dialogRef.current.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href]')]
      if (!elements.length) { event.preventDefault(); return }
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialogRef.current)) {
        event.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => { document.removeEventListener('keydown', handleKey); previousFocus?.focus() }
  }, [])

  const impacts = preflight?.affected_exams || []
  const blockers = (preflight?.blockers || []).filter((blocker) => blocker !== 'schedule_reschedule_required')
  const expired = Boolean(preflight?.suggestion_valid_until_at && now >= new Date(preflight.suggestion_valid_until_at).getTime())
  const ready = exam.status === 'sealed' && exam.rosterStatus === 'ready'
  const recoverable = impacts.length > 0 && !blockers.length && impacts.every((impact) => impact.status === 'sealed' && impact.suggested_start_at)
  const hasSuggestions = impacts.every((impact) => impact.suggested_start_at)

  const refresh = async () => {
    setBusy('checking')
    setError('')
    try { acceptPreflight(await gateway.exams.activationPreflight(exam.id)) }
    catch (requestError) { setPreflight(null); setError(requestError.userMessage || 'Could not check the activation timetable.') }
    finally { setBusy('') }
  }

  const saveRecovery = async () => {
    if (!recoverable || expired || !ready || busy) return
    if (!reason.trim()) { setError('Enter a reason for changing the affected timetable.'); return }
    const changes = []
    for (const impact of impacts) {
      const date = new Date(times[impact.exam_id])
      if (!times[impact.exam_id] || !Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) {
        setError(`Choose a future start time for ${impact.title}.`)
        return
      }
      changes.push({ exam_id: impact.exam_id, scheduled_start_at: date.toISOString() })
    }
    setBusy('saving')
    setError('')
    try {
      const result = await gateway.exams.rescheduleActivationImpact(exam.id, changes, reason.trim())
      acceptPreflight(result.preflight)
      setSaved(true)
      try { await onRefresh() }
      catch { setError('The timetable was saved, but the examination list could not refresh. Check again before activating.') }
    } catch (requestError) {
      // The failed batch changes nothing. Refresh the real timetable rather than
      // displaying the backend's rejected simulation as a saved schedule.
      try { acceptPreflight(await gateway.exams.activationPreflight(exam.id)) }
      catch { setPreflight(null) }
      setError(requestError.userMessage || 'The timetable could not be saved. Review the refreshed times and try again.')
    } finally { setBusy('') }
  }

  const activate = async () => {
    if (busy || !ready || !preflight?.can_activate) return
    setBusy('activating')
    setError('')
    try {
      // Check again immediately before activation; activate also validates under
      // the backend lock, covering changes between these two requests.
      const latest = await gateway.exams.activationPreflight(exam.id)
      acceptPreflight(latest)
      if (!latest.can_activate) { setSaved(false); return }
      await gateway.exams.activateExam(exam.id)
      // Activation has succeeded even if refreshing the list fails afterwards.
      try { await onRefresh() } catch { /* The workspace owns list-load errors. */ }
      onActivated()
    } catch (requestError) {
      setSaved(false)
      try { acceptPreflight(await gateway.exams.activationPreflight(exam.id)) }
      catch { setPreflight(null) }
      setError(requestError.userMessage || 'Could not activate this examination. Review the timetable and try again.')
    } finally { setBusy('') }
  }

  return createPortal(
    <div className="admin-ops-confirm-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel() }}>
      <section ref={dialogRef} tabIndex={-1} className="admin-ops-confirm admin-ops-activation-review" role="alertdialog" aria-modal="true" aria-labelledby="activation-review-title" aria-describedby="activation-review-description" aria-busy={Boolean(busy)}>
        <header className="admin-ops-confirm__heading admin-ops-activation-header">
          <span><Icon name="operations" size={22} /></span>
          <div><h2 id="activation-review-title">{impacts.length ? 'Resolve timetable clashes' : 'Activate this examination?'}</h2><p id="activation-review-description">{impacts.length ? 'Review the affected sittings here before opening this examination to candidates.' : 'Check the timetable, then open this sitting to candidates on the prepared roster.'}</p></div>
        </header>
        <div className="admin-ops-activation-body">
        <div className="admin-ops-confirm__exam"><span>Examination</span><strong>{exam.title}</strong><small>Scheduled {displayTime(exam.scheduledStartAt)}</small>{preflight?.projected_end_at && <small>Starting now: projected finish {displayTime(preflight.projected_end_at)}</small>}</div>
        {busy === 'checking' && <p role="status">Checking the activation timetable…</p>}
        {!ready && <Notice tone="warning">This examination is no longer ready for activation. Close this review and check its current state.</Notice>}
        {blockers.map((blocker) => <Notice key={blocker} tone="warning">{BLOCKER_COPY[blocker] || `Activation is blocked: ${blocker.replaceAll('_', ' ')}.`}</Notice>)}
        {preflight?.conflicting_operational_exam_ids?.map((id) => <div className="admin-ops-activation-blocker" key={id}><strong>{exams.find((item) => item.id === id)?.title || 'Conflicting examination'}</strong><span>{exams.find((item) => item.id === id)?.statusLabel || 'Operational sitting'}</span></div>)}
        {impacts.length > 0 && <>
          <div className="admin-ops-activation-summary"><div><strong>{impacts.length} affected sitting{impacts.length === 1 ? '' : 's'}</strong><span>Times shown in {Intl.DateTimeFormat().resolvedOptions().timeZone}.</span></div>{recoverable && <button type="button" className="admin-ops-button" disabled={Boolean(busy) || !hasSuggestions} onClick={() => setTimes(suggestedTimes(preflight))}>Use suggested times</button>}</div>
          <div className="admin-ops-activation-chain">{impacts.map((impact) => <article key={impact.exam_id}>
            <strong>{impact.title}</strong><p>{impact.reason}</p>
            <div className="admin-ops-activation-times"><div><span>Current start</span><strong>{displayTime(impact.scheduled_start_at)}</strong></div><div><span>Suggested start</span><strong>{displayTime(impact.suggested_start_at)}</strong>{impact.suggested_end_at && <small>Finish {displayTime(impact.suggested_end_at)}</small>}</div></div>
            {recoverable && <label><span>New start for {impact.title}</span><input type="datetime-local" step="1" value={times[impact.exam_id] || ''} disabled={Boolean(busy)} onChange={(event) => setTimes((current) => ({ ...current, [impact.exam_id]: event.target.value }))} /></label>}
          </article>)}</div>
          {!recoverable && !blockers.length && <Notice tone="warning">A safe start cannot be calculated for every affected sitting. Resolve the blocking operational examination, then check again.</Notice>}
          {recoverable && <>
            <label className="admin-ops-confirm__reason"><span>Reason for timetable changes</span><textarea rows="2" maxLength={500} disabled={Boolean(busy)} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain the delay or timetable adjustment." /></label>
          </>}
        </>}
        {expired && impacts.length > 0 && <Notice tone="warning">These suggestions have expired. Check again for safe start times before saving.</Notice>}
        {saved && !impacts.length && <Notice tone="success">The affected timetable is saved. This examination has not been activated yet.</Notice>}
        {!impacts.length && preflight?.can_activate && <div className="admin-ops-confirm__warning"><Icon name="info" size={17} /><span>Activation opens this sitting to the prepared roster. Later enrollment changes will not rewrite the active roster.</span></div>}
        {error && <Notice tone="danger">{error}</Notice>}
        </div>
        <footer className="admin-ops-confirm__actions admin-ops-activation-footer">
          <button type="button" className="admin-ops-confirm__cancel" disabled={Boolean(busy)} onClick={onCancel}>Go back</button>
          <button type="button" className="admin-ops-confirm__cancel" disabled={Boolean(busy)} onClick={() => void refresh()}>Check again</button>
          {impacts.length > 0 ? <button type="button" className="admin-ops-confirm__submit" disabled={Boolean(busy) || !recoverable || expired || !ready} onClick={() => void saveRecovery()}>{busy === 'saving' ? 'Saving…' : 'Save affected timetable'}</button> : <button type="button" className="admin-ops-confirm__submit" disabled={Boolean(busy) || !preflight?.can_activate || !ready} onClick={() => void activate()}>{busy === 'activating' ? 'Activating…' : 'Activate examination'}</button>}
        </footer>
      </section>
    </div>,
    // The detail page is a CSS query container, which contains fixed-position
    // descendants. Portal above it so the overlay covers the entire viewport.
    document.querySelector('.weave-app') || document.body,
  )
}
