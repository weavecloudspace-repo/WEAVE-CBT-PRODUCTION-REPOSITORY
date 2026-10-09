import { bulkTargetId } from './rosterBulkTargets'
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { RiAddLine, RiCloseLine, RiForbidLine, RiTimeLine, RiPauseCircleLine, RiSettings3Line, RiArrowRightLine } from '@remixicon/react'
import { Notice } from '../../../shared/ui'
import '../admin-roster-bulk.css'

const ALL_PAGE_SIZE = 100



export function RosterBulkActions(props) {
  const launcherInstance = Object.prototype.hasOwnProperty.call(props, 'disabled')
  const {
    exam,
    payload,
    gateway,
    action,
    onActionChange,
    selectedTargets,
    onSelectedTargetsChange,
    onChanged,
    onOpenOperations,
    disabled = false,
  } = props
  const [menuOpen, setMenuOpen] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [expiry, setExpiry] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [selectingAll, setSelectingAll] = useState(false)
  const dialogRef = useRef(null)
  const menuRef = useRef(null)
  const triggerRef = useRef(null)
  const menuId = useId()

  const options = bulkOptions(exam, payload)

  useEffect(() => {
    if (dialogOpen) dialogRef.current?.showModal()
  }, [dialogOpen])

  useEffect(() => {
    if (!menuOpen) return undefined
    menuRef.current?.querySelector('[role="menuitem"]')?.focus()
    const closeOutside = (event) => {
      if (!menuRef.current?.contains(event.target)) setMenuOpen(false)
    }
    const closeOnEscape = (event) => {
      const items = Array.from(menuRef.current?.querySelectorAll('[role="menuitem"]') || [])
      const index = items.indexOf(document.activeElement)
      if (index >= 0 && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault()
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
        items[next]?.focus()
      }
      if (event.key === 'Escape') {
        setMenuOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [menuOpen])

  const chooseAction = (nextAction) => {
    setMenuOpen(false)
    setError('')
    onSelectedTargetsChange(new Set())
    onActionChange(nextAction)
  }

  const cancelSelection = () => {
    if (busy) return
    setError('')
    setReason('')
    setExpiry('')
    setDialogOpen(false)
    onSelectedTargetsChange(new Set())
    onActionChange(null)
  }

  const selectAll = async () => {
    if (!action || selectingAll) return
    setSelectingAll(true)
    setError('')
    try {
      const targets = new Set()
      let offset = 0
      let total = 0
      do {
        const params = { offset, limit: ALL_PAGE_SIZE }
        if (action === 'block' || action === 'late-start') {
          params.status = 'eligible'
          params.attempt_state = 'not_started'
        } else if (action === 'interrupt') {
          params.attempt_state = 'in_progress'
        }
        const response = await gateway.candidates.listExamRoster(exam.id, params)
        const candidates = response?.candidates || []
        candidates.forEach((candidate) => {
          const target = bulkTargetId(action, candidate)
          if (target) targets.add(target)
        })
        total = Number(response?.total) || 0
        offset += ALL_PAGE_SIZE
      } while (offset < total)
      onSelectedTargetsChange(targets)
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not select all candidates for this action.')
    } finally {
      setSelectingAll(false)
    }
  }

  const confirm = async () => {
    const normalizedReason = reason.trim()
    if (!normalizedReason) {
      setError('Enter one reason that will apply to every selected candidate.')
      return
    }
    const targets = [...selectedTargets]
    if (!targets.length) {
      setError('Select at least one candidate.')
      return
    }

    let expiresAt = null
    if (action === 'late-start' && expiry) {
      const parsed = new Date(expiry)
      if (Number.isNaN(parsed.getTime())) {
        setError('Enter a valid late-start expiry date and time.')
        return
      }
      expiresAt = parsed.toISOString()
    }

    setBusy(true)
    setError('')
    try {
      if (action === 'block') {
        await gateway.candidates.bulkBlockCandidates(exam.id, targets, normalizedReason)
      } else if (action === 'late-start') {
        await gateway.candidates.bulkGrantLateStart(exam.id, {
          candidate_ids: targets,
          reason: normalizedReason,
          expires_at: expiresAt,
        })
      } else if (action === 'interrupt') {
        await gateway.attempts.interruptAttempts(exam.id, targets, normalizedReason)
      }
      setDialogOpen(false)
      setReason('')
      setExpiry('')
      onSelectedTargetsChange(new Set())
      onActionChange(null)
      await onChanged?.()
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not complete this bulk action.')
    } finally {
      setBusy(false)
    }
  }

  // AdminRosterDetailPage deliberately keeps the compact launcher in the page
  // filter toolbar and the selection toolbar in the content flow. Once an action is
  // chosen, only the content instance should render the toolbar.
  if (action && launcherInstance) return null

  if (action) {
    return (
      <>
        <div className="admin-roster-bulk-toolbar" role="region" aria-label={`${bulkLabel(action)} selection`}>
          <div>
            <strong>{bulkLabel(action)}</strong>
            <span>{selectedTargets.size} selected</span>
          </div>
          <div className="admin-roster-bulk-toolbar__actions">
            <button type="button" className="admin-roster-bulk-secondary" disabled={selectingAll || busy} onClick={() => void selectAll()}>
              {selectingAll ? 'Selecting…' : selectAllLabel(action)}
            </button>
            <button type="button" className="admin-roster-bulk-secondary" disabled={!selectedTargets.size || busy} onClick={() => onSelectedTargetsChange(new Set())}>Clear</button>
            <button type="button" className="admin-roster-bulk-primary" disabled={!selectedTargets.size || busy} onClick={() => { setError(''); setDialogOpen(true) }}>
              Continue{selectedTargets.size ? ` (${selectedTargets.size})` : ''}
            </button>
            <button type="button" className="admin-roster-bulk-icon" aria-label="Cancel bulk selection" disabled={busy} onClick={cancelSelection}><RiCloseLine size={18} /></button>
          </div>
        </div>
        {error && !dialogOpen && <Notice tone="danger">{error}</Notice>}
        {dialogOpen && createPortal(
          <dialog ref={dialogRef} className="admin-roster-bulk-dialog" aria-labelledby="roster-bulk-title" onCancel={(event) => { event.preventDefault(); if (!busy) setDialogOpen(false) }}>
            <header>
              <div><span>Bulk candidate action</span><h2 id="roster-bulk-title">{bulkLabel(action)}</h2><p>{selectedTargets.size} candidate{selectedTargets.size === 1 ? '' : 's'} selected</p></div>
              <button type="button" aria-label="Close bulk action dialog" disabled={busy} onClick={() => setDialogOpen(false)}>×</button>
            </header>
            <div className="admin-roster-bulk-dialog__body">
              <p>{bulkDescription(action)}</p>
              {error && <Notice tone="danger">{error}</Notice>}
              <label><span>Reason <small>applies to every selected candidate</small></span><textarea autoFocus maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Enter one reason for this bulk action." /></label>
              {action === 'late-start' && <label><span>Expires at <small>(optional)</small></span><input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} /></label>}
              <footer>
                <button type="button" className="admin-roster-bulk-secondary" disabled={busy} onClick={() => setDialogOpen(false)}>Cancel</button>
                <button type="button" className={`admin-roster-bulk-primary${action === 'block' || action === 'interrupt' ? ' is-danger' : ''}`} disabled={busy} onClick={() => void confirm()}>{busy ? 'Applying…' : `${bulkVerb(action)} ${selectedTargets.size}`}</button>
              </footer>
            </div>
          </dialog>,
          document.body,
        )}
      </>
    )
  }

  return (
    <div ref={menuRef} className="admin-roster-bulk-menu-wrap">
      <button ref={triggerRef} type="button" className="admin-roster-bulk-add" aria-label="Open roster operations" aria-haspopup="menu" aria-controls={menuOpen ? menuId : undefined} aria-expanded={menuOpen} disabled={disabled} onClick={() => setMenuOpen((value) => !value)}><RiAddLine size={18} aria-hidden="true" /><span>Operations</span></button>
      {menuOpen && (
        <div id={menuId} className="admin-roster-bulk-menu" role="menu" aria-label="Roster operations">
          <strong>Roster operations</strong>
          {onOpenOperations && <button className="admin-roster-bulk-menu__lifecycle" type="button" role="menuitem" onClick={() => { setMenuOpen(false); onOpenOperations() }}><span className="admin-roster-bulk-menu__icon"><RiSettings3Line size={20} aria-hidden="true" /></span><span className="admin-roster-bulk-menu__copy"><strong>Exam lifecycle controls</strong><small>Manage the current sitting.</small></span><RiArrowRightLine size={17} aria-hidden="true" /></button>}
          {options.map((option) => {
            const ActionIcon = option.action === 'block' ? RiForbidLine : option.action === 'interrupt' ? RiPauseCircleLine : RiTimeLine
            return <button key={option.action} className={`admin-roster-bulk-menu__action is-${option.action}`} type="button" role="menuitem" onClick={() => chooseAction(option.action)}><span className="admin-roster-bulk-menu__icon"><ActionIcon size={20} aria-hidden="true" /></span><span className="admin-roster-bulk-menu__copy"><strong>{option.label}</strong><small>{bulkDescription(option.action)}</small></span><span className="admin-roster-bulk-menu__count" aria-label={`${option.count} available`}>{option.count}</span></button>
          })}
          {!options.length && <p>No candidate bulk actions are available for this exam state.</p>}
        </div>
      )}
    </div>
  )
}

function bulkOptions(exam, payload) {
  if (!exam || !payload) return []
  if (exam.status === 'sealed') {
    return payload.eligible_not_started_count > 0
      ? [{ action: 'block', label: 'Bulk block candidates', count: payload.eligible_not_started_count }]
      : []
  }
  if (exam.status === 'active') {
    const options = []
    if (payload.late_start_required_count > 0) options.push({ action: 'late-start', label: 'Grant late-start access', count: payload.late_start_required_count })
    if (payload.in_progress_count > 0) options.push({ action: 'interrupt', label: 'Interrupt active attempts', count: payload.in_progress_count })
    return options
  }
  return []
}

function selectAllLabel(action) {
  if (action === 'interrupt') return 'Select all writing'
  if (action === 'late-start') return 'Select all requiring access'
  return 'Select all eligible'
}

function bulkLabel(action) {
  if (action === 'block') return 'Bulk block candidates'
  if (action === 'late-start') return 'Bulk late-start authorization'
  return 'Bulk interrupt attempts'
}

function bulkDescription(action) {
  if (action === 'block') return 'Selected candidates will be prevented from starting this examination.'
  if (action === 'late-start') return 'Selected candidates will be allowed to start after the normal entry deadline.'
  return 'Selected active attempts will be paused together. Saved answers remain safe and each candidate timer stops until resumed.'
}

function bulkVerb(action) {
  if (action === 'block') return 'Block'
  if (action === 'late-start') return 'Grant access to'
  return 'Interrupt'
}
