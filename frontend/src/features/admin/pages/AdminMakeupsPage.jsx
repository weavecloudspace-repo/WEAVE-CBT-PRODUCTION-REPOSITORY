import { useCallback, useEffect, useRef, useState } from 'react'
import { Notice, SelectControl, StatusBadge } from '../../../shared/ui'
import { useToast } from '../../../shared/ui/useToast'
import '../admin-makeups.css'

const label = (value) => value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
const PAGE_SIZE = 50

export function AdminMakeupsPage({ examId, adminData, gateway, onNavigate }) {
  const [payload, setPayload] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(0)
  const [page, setPage] = useState(0)
  const [query, setQuery] = useState('')
  const [level, setLevel] = useState('all')
  const [status, setStatus] = useState('all')
  const [selected, setSelected] = useState([])
  const [operation, setOperation] = useState(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const dialog = useRef(null)
  const { showSuccess, showError } = useToast()
  const exam = adminData.exams.find((item) => item.id === examId)

  useEffect(() => {
    const controller = new AbortController()
    let timer
    const refresh = async (silent = false) => {
      if (!silent) setLoading(true)
      try {
        const result = examId
          ? await gateway.makeups.getMakeupReview(examId, { offset: page * PAGE_SIZE, limit: PAGE_SIZE }, { signal: controller.signal })
          : await gateway.makeups.listMakeupReviewSets({ signal: controller.signal })
        if (!controller.signal.aborted) { setPayload(result); setError('') }
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure.userMessage || 'Could not load makeup examinations. Try refreshing.')
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
          timer = window.setTimeout(() => refresh(true), 10000)
        }
      }
    }
    void refresh()
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [examId, gateway, page, version])

  useEffect(() => {
    if (operation) dialog.current?.showModal()
  }, [operation])

  const closeDialog = useCallback(() => {
    if (busy) return
    dialog.current?.close()
    setOperation(null)
    setReason('')
  }, [busy])

  const rows = (payload?.candidates || []).filter((item) =>
    (status === 'all' || item.state === status)
    && `${item.name} ${item.admission_number} ${item.class_name}`.toLowerCase().includes(query.toLowerCase()),
  )
  const eligible = rows.filter((item) => item.can_approve)
  const selectedRows = rows.filter((item) => selected.includes(item.id) && item.can_approve)
  const submit = async (event) => {
    event.preventDefault()
    if (busy || !reason.trim()) return
    setBusy(true)
    const failures = []
    let succeeded = 0
    try {
      if (operation.kind === 'revoke') {
        await gateway.makeups.revokeMakeup(operation.row.authorization_id, reason.trim())
        succeeded = 1
      } else {
        for (const item of operation.rows) {
          try {
            await gateway.makeups.approveMakeup(item.id, reason.trim(), { successMessage: false })
            succeeded += 1
          } catch (failure) { failures.push(`${item.name}: ${failure.userMessage || 'Approval failed.'}`) }
        }
        if (succeeded) showSuccess(`${succeeded} makeup approval${succeeded === 1 ? '' : 's'} granted.`)
      }
    } catch (failure) { failures.push(failure.userMessage || 'Makeup action failed.') }
    finally {
      setBusy(false)
      dialog.current?.close()
      setOperation(null)
      setReason('')
      setSelected([])
      setVersion((value) => value + 1)
      if (failures.length) showError(failures.join('\n'))
    }
  }

  const summaries = new Map((payload?.exams || []).map((item) => [item.exam_id, item]))
  const exams = adminData.exams.filter((item) => item.status === 'closed'
    && (level === 'all' || item.academicLevelId === level)
    && `${item.title} ${item.subjectName}`.toLowerCase().includes(query.toLowerCase()))
  const levels = [...new Map(adminData.exams.filter((item) => item.academicLevelId).map((item) => [item.academicLevelId, { value: item.academicLevelId, label: item.academicLevelName }])).values()]

  return (
    <div className="admin-makeups-page">
      {examId && <button className="teacher-secondary-action" onClick={() => onNavigate('makeups')}>← Back to makeups</button>}
      <header className="admin-makeups-heading"><div><h1>{examId ? exam?.title || 'Makeup examination' : 'Makeup examinations'}</h1><p>{examId ? 'Approve missed students, check readiness and follow their progress.' : 'Manage approved sittings for students who missed a closed examination.'}</p></div><button className="teacher-secondary-action" disabled={loading} onClick={() => setVersion((value) => value + 1)}>Refresh</button></header>
      {(error || adminData.error) && <Notice tone="danger">{error || adminData.error}</Notice>}
      {examId && payload && <section className="admin-makeup-readiness" aria-label="Makeup readiness">
        <StatusBadge tone={payload.available ? 'success' : 'warning'}>{payload.available ? 'Available to approved students' : 'Waiting for readiness'}</StatusBadge>
        <details className="admin-makeup-info">
          <summary><span aria-hidden="true" className="admin-makeup-info-icon">i</span> Readiness details</summary>
          <div className="admin-makeup-info-content">
        <p>{payload.blockers.length ? `Normal examinations still unfinished: ${payload.blockers.join(', ')}.` : 'The academic level’s scheduled examination cycle is complete.'}</p>
        <p>{payload.fresh_question_count} unused active questions available · {payload.required_question_count} required.{payload.fresh_question_count < payload.required_question_count ? ' Add enough unused questions before students start.' : ''}</p>
        <small>Approval does not override these checks. Students receive the original paper’s full duration from their own start time.</small>
          </div>
        </details>
      </section>}
      <div className="admin-makeups-filters">
        <label>Search {examId ? 'students on this page' : 'examinations'}<input type="search" value={query} onChange={(event) => { setQuery(event.target.value); setSelected([]) }} placeholder={examId ? 'Name, admission number or class' : 'Exam or subject name'} /></label>
        {examId ? <SelectControl label="Makeup status" value={status} onChange={(value) => { setStatus(value); setSelected([]) }} options={[{ value: 'all', label: 'All states' }, ...['awaiting_approval', 'approved', 'writing', 'paused', 'completed', 'revoked', 'terminated', 'needs_review', 'blocked', 'withdrawn'].map((value) => ({ value, label: label(value) }))]} /> : <SelectControl label="Academic level" value={level} onChange={setLevel} options={[{ value: 'all', label: 'All levels' }, ...levels]} />}
      </div>
      {!examId ? <div className="admin-makeup-exams">
        {loading && !payload ? <p role="status">Loading makeup examinations…</p> : exams.map((item) => {
          const counts = summaries.get(item.id)
          return <article key={item.id}><div><h2>{item.title}</h2><p>{item.academicLevelName} · {item.subjectName}</p><small>{item.scheduledStartAt ? new Date(item.scheduledStartAt).toLocaleString() : 'No original schedule'}</small></div><div className="admin-makeup-counts"><span>{counts?.awaiting_approval ?? 0} awaiting approval</span><span>{counts?.approved ?? 0} approved</span><span>{counts?.completed ?? 0} completed</span></div><button className="teacher-secondary-action" onClick={() => onNavigate('makeup-detail', { selectedExamId: item.id })}>Manage makeups →</button></article>
        })}
        {!loading && !exams.length && <p>No closed examinations match these filters. Makeup approval becomes available after the original exam closes.</p>}
      </div> : <>
        <div className="admin-makeup-bulk"><span>{selectedRows.length} selected · {eligible.length} eligible on this page</span><button className="teacher-secondary-action" disabled={!eligible.length || loading || Boolean(error)} onClick={() => setSelected(eligible.map((item) => item.id))}>Select all eligible</button><button className="teacher-primary-action" disabled={!selectedRows.length || loading || Boolean(error)} onClick={() => setOperation({ kind: 'approve', rows: selectedRows })}>Approve selected ({selectedRows.length})</button></div>
        <div className="admin-makeup-table-scroll"><table><thead><tr><th>Select</th><th>Student</th><th>Class</th><th>Status</th><th>Progress / score</th><th>Action</th></tr></thead><tbody>
          {rows.map((item) => <tr key={item.id}><td><input type="checkbox" aria-label={`Select ${item.name}`} checked={selected.includes(item.id)} disabled={!item.can_approve || loading || Boolean(error)} onChange={() => setSelected((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id])} /></td><td><strong>{item.name}</strong><small>{item.admission_number}</small></td><td>{item.class_name}</td><td><StatusBadge tone={item.state === 'completed' ? 'success' : item.state === 'paused' ? 'warning' : 'neutral'}>{label(item.state)}</StatusBadge></td><td>{item.percentage !== null ? `${item.percentage}%` : ['writing', 'paused'].includes(item.state) ? `${Math.ceil(item.remaining_seconds / 60)} min remaining` : '—'}</td><td>{item.can_approve && <button className="teacher-secondary-action" disabled={Boolean(error) || loading} onClick={() => setOperation({ kind: 'approve', rows: [item] })}>Approve</button>}{item.can_revoke && <button className="teacher-secondary-action" disabled={Boolean(error) || loading} onClick={() => setOperation({ kind: 'revoke', row: item })}>Revoke</button>}{item.state === 'completed' && <button className="teacher-secondary-action" onClick={() => onNavigate('result-detail', { selectedExamId: examId })}>View results</button>}</td></tr>)}
          {!rows.length && <tr><td colSpan="6">{loading ? 'Loading students…' : 'No students match this view.'}</td></tr>}
        </tbody></table></div>
        <footer className="admin-makeup-pagination"><span>{payload?.total || 0} students · Page {page + 1}</span><button className="teacher-secondary-action" disabled={!page || loading} onClick={() => { setPage(page - 1); setSelected([]) }}><span aria-hidden="true">←</span> Previous</button><button className="teacher-secondary-action" disabled={loading || (page + 1) * PAGE_SIZE >= (payload?.total || 0)} onClick={() => { setPage(page + 1); setSelected([]) }}>Next <span aria-hidden="true">→</span></button></footer>
      </>}
      <dialog ref={dialog} className="admin-makeup-dialog" onCancel={(event) => { event.preventDefault(); closeDialog() }}>
        {operation && <form onSubmit={submit}><h2>{operation.kind === 'approve' ? `Approve ${operation.rows.length} makeup sitting${operation.rows.length === 1 ? '' : 's'}?` : `Revoke ${operation.row.name}’s approval?`}</h2><p>{exam?.title}</p><p>{operation.kind === 'approve' ? 'Students can start once the normal exam cycle and question-bank checks are satisfied.' : 'This removes permission to start. It does not change a submitted score.'}</p><label>Reason<textarea required maxLength={1024} value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy} /></label><footer><button type="button" className="teacher-secondary-action" disabled={busy} onClick={closeDialog}>Cancel</button><button className="teacher-primary-action" disabled={busy || !reason.trim()}>{busy ? 'Saving…' : operation.kind === 'approve' ? 'Confirm approval' : 'Revoke approval'}</button></footer></form>}
      </dialog>
    </div>
  )
}
