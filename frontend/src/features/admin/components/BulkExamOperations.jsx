import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '../../../shared/icons/Icon'

const OPERATIONS = [
  { id: 'activate', label: 'Activate', icon: 'play', copy: 'Open due, sealed sittings with ready rosters.' },
  { id: 'suspend', label: 'Suspend', icon: 'pause', copy: 'Pause active sittings and preserve candidate time.' },
  { id: 'resume', label: 'Resume', icon: 'play', copy: 'Continue suspended sittings.' },
  { id: 'close', label: 'Close', icon: 'stop', copy: 'End active or suspended sittings and finalize attempts.', danger: true },
  { id: 'cancel', label: 'Cancel', icon: 'close', copy: 'Invalidate sealed, active, or suspended sittings.', danger: true },
]

function eligible(exam, operation, now) {
  if (operation === 'activate') return exam.status === 'sealed' && exam.rosterStatus === 'ready' && Date.parse(exam.scheduledStartAt) <= now
  if (operation === 'suspend') return exam.status === 'active'
  if (operation === 'resume') return exam.status === 'suspended'
  if (operation === 'close') return ['active', 'suspended'].includes(exam.status)
  if (operation === 'cancel') return ['sealed', 'active', 'suspended'].includes(exam.status)
  return false
}

export function BulkExamOperations({ exams, scopeKey, gateway, onRefresh, onOpen, disabled, children }) {
  const [now, setNow] = useState(() => Date.now())
  const [menuOpen, setMenuOpen] = useState(false)
  const [operation, setOperation] = useState('')
  const [selection, setSelection] = useState({ scope: scopeKey, ids: new Set() })
  const [review, setReview] = useState(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState(null)
  const rootRef = useRef(null)
  const triggerRef = useRef(null)
  const dialogRef = useRef(null)
  const choice = OPERATIONS.find((item) => item.id === operation)
  const available = exams.filter((exam) => eligible(exam, operation, now))
  // A filter/date change never carries hidden selections into a batch.
  const selected = selection.scope === scopeKey ? available.filter((exam) => selection.ids.has(exam.id)) : []
  const selectedIds = new Set(selected.map((exam) => exam.id))
  if (selection.scope !== scopeKey) setSelection({ scope: scopeKey, ids: new Set() })

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 10000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!menuOpen) return undefined
    rootRef.current.querySelector('[role="menuitem"]:not(:disabled)')?.focus()
    const dismiss = (event) => {
      if (event.type === 'pointerdown' && !rootRef.current.contains(event.target)) setMenuOpen(false)
      if (event.type === 'keydown' && event.key === 'Escape') { setMenuOpen(false); triggerRef.current?.focus() }
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', dismiss)
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', dismiss) }
  }, [menuOpen])

  useEffect(() => { if (review) dialogRef.current?.showModal() }, [review])

  const setIds = (ids) => setSelection({ scope: scopeKey, ids })
  const toggle = (exam) => {
    if (busy || disabled || !eligible(exam, operation, now)) return
    const next = new Set(selectedIds)
    if (next.has(exam.id)) next.delete(exam.id)
    else next.add(exam.id)
    setIds(next)
  }
  const choose = (id) => {
    setOperation(id); setIds(new Set()); setMenuOpen(false); setError(''); setResults(null)
  }
  const confirm = async () => {
    if (busy || results || !review?.exams.length) return
    if (['suspend', 'cancel'].includes(review.operation.id) && !reason.trim()) {
      setError('Enter an audit reason for this operation.'); return
    }
    setBusy(true); setError('')
    const collected = []
    // Keep requests bounded while allowing selection of every visible exam.
    for (let offset = 0; offset < review.exams.length; offset += 100) {
      const chunk = review.exams.slice(offset, offset + 100)
      try {
        const response = await gateway.exams.batchExamOperation(review.operation.id, chunk.map((exam) => exam.id), reason.trim() || undefined)
        collected.push(...chunk.map((exam) => response.results.find((result) => result.exam_id === exam.id) || { exam_id: exam.id, succeeded: false, error: 'No result received. Refresh this sitting before retrying.' }))
      } catch (requestError) {
        collected.push(...chunk.map((exam) => ({ exam_id: exam.id, succeeded: false, error: requestError.userMessage || 'Outcome could not be confirmed. Refresh before retrying.' })))
        // Do not send more mutations after a transport or request-level failure.
        collected.push(...review.exams.slice(offset + 100).map((exam) => ({ exam_id: exam.id, succeeded: false, error: 'Not attempted because the earlier request failed.' })))
        break
      }
    }
    setResults(collected)
    setOperation('')
    setIds(new Set())
    setReason('')
    try { await onRefresh({ silent: false }) }
    catch { setError('The batch finished, but the examination list could not refresh. Check current state before retrying.') }
    finally { setBusy(false) }
  }
  const closeReview = () => { if (!busy) { setReview(null); setResults(null); setError('') } }

  return <>
    <div className="admin-ops-bulk-bar" ref={rootRef}>
      {!operation ? <>
        <div><strong>Manage multiple sittings</strong><span>Choose an operation, then select exams in this view.</span></div>
        <div className="admin-ops-bulk-menu-wrap">
          <button ref={triggerRef} type="button" className="admin-ops-button" aria-haspopup="menu" aria-expanded={menuOpen} disabled={disabled || !gateway?.exams?.batchExamOperation} onClick={() => setMenuOpen((value) => !value)}><Icon name="operations" size={17} /> Bulk operations <Icon name="chevronDown" size={15} /></button>
          {menuOpen && <div className="admin-ops-bulk-menu" role="menu" aria-label="Bulk exam operations" onKeyDown={(event) => {
            if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
            event.preventDefault()
            const items = [...event.currentTarget.querySelectorAll('[role="menuitem"]:not(:disabled)')]
            if (!items.length) return
            const index = items.indexOf(document.activeElement)
            items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus()
          }}>{OPERATIONS.map((item) => {
            const count = exams.filter((exam) => eligible(exam, item.id, now)).length
            return <button key={item.id} type="button" role="menuitem" disabled={!count} onClick={() => choose(item.id)}><Icon name={item.icon} size={18} /><span><strong>{item.label} examinations</strong><small>{item.copy}</small></span><b>{count}</b></button>
          })}</div>}
        </div>
      </> : <>
        <div><strong>{choice.label} examinations</strong><span>{selected.length} selected · {available.length} eligible in this view</span></div>
        <div className="admin-ops-bulk-buttons">
          <button className="admin-ops-button" type="button" disabled={busy || disabled || !available.length} onClick={() => setIds(selected.length === available.length ? new Set() : new Set(available.map((exam) => exam.id)))}>{selected.length && selected.length === available.length ? 'Clear selection' : 'Select all eligible'}</button>
          <button className="admin-ops-button admin-ops-button--primary" type="button" disabled={busy || disabled || !selected.length} onClick={() => { setReason(''); setError(''); setResults(null); setReview({ operation: choice, exams: selected }) }}>Continue ({selected.length})</button>
          <button className="admin-ops-button" type="button" disabled={busy} aria-label="Exit bulk selection" onClick={() => { setOperation(''); setIds(new Set()) }}><Icon name="close" size={17} /></button>
        </div>
      </>}
    </div>
    {children({ operation, selectedIds, canSelect: (exam) => eligible(exam, operation, now), toggle, busy: busy || disabled })}
    {review && createPortal(<dialog ref={dialogRef} className="admin-ops-bulk-dialog" aria-labelledby="bulk-exam-title" onCancel={(event) => { event.preventDefault(); closeReview() }}>
      <header><span><Icon name={review.operation.icon} size={22} /></span><div><h2 id="bulk-exam-title">{results ? 'Operation results' : `${review.operation.label} ${review.exams.length} examination${review.exams.length === 1 ? '' : 's'}?`}</h2><p>{results ? `${results.filter((item) => item.succeeded).length} succeeded · ${results.filter((item) => !item.succeeded).length} need review` : review.operation.copy}</p></div></header>
      <div className="admin-ops-bulk-dialog__body">
        {!results && <p className={review.operation.danger ? 'admin-ops-bulk-warning is-danger' : 'admin-ops-bulk-warning'}>{review.operation.danger ? 'This is permanent for every selected sitting. ' : ''}Each exam is validated separately. Eligible exams proceed; blocked exams stay unchanged. Activation does not automatically reschedule later sittings.</p>}
        <ul>{review.exams.map((exam) => {
          const result = results?.find((item) => item.exam_id === exam.id)
          return <li key={exam.id}><div><strong>{exam.title}</strong><small>{exam.academicLevelName} · {exam.statusLabel || exam.status}</small>{result && <p className={result.succeeded ? 'is-success' : 'is-error'}>{result.succeeded ? ['closing', 'cancelling'].includes(result.status) ? 'Requested · finalization in progress' : 'Completed' : result.error}{result.warning && ` ${result.warning}`}</p>}</div>{result && !result.succeeded && <button className="admin-ops-button" type="button" disabled={busy} onClick={() => { closeReview(); onOpen(exam) }}>Review sitting <Icon name="chevronRight" size={15} /></button>}</li>
        })}</ul>
        {!results && ['suspend', 'resume', 'cancel'].includes(review.operation.id) && <label className="admin-ops-confirm__reason"><span>Reason {review.operation.id === 'resume' ? '(optional)' : '(required)'}</span><textarea rows="2" maxLength={500} disabled={busy} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Applies to every selected examination." /></label>}
        {error && <p className="admin-ops-bulk-warning is-danger" role="alert">{error}</p>}
      </div>
      <footer><button type="button" className="admin-ops-button" disabled={busy} onClick={closeReview}>{results ? 'Done' : 'Go back'}</button>{!results && <button type="button" className={`admin-ops-button admin-ops-button--primary${review.operation.danger ? ' is-danger' : ''}`} disabled={busy} onClick={() => void confirm()}>{busy ? 'Applying…' : `${review.operation.label} selected examinations`}</button>}</footer>
    </dialog>, document.querySelector('.weave-app') || document.body)}
  </>
}
