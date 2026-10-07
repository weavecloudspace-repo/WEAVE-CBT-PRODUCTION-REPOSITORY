import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  RiArrowLeftLine,
  RiArrowRightLine,
  RiCheckLine,
  RiCloseCircleLine,
  RiRefreshLine,
  RiSearchLine,
  RiTimeLine,
} from '@remixicon/react'
import { buildAcademicLevels, listSubjectsForLevel } from '../../../shared/academics/authoringScope'
import { Icon } from '../../../shared/icons/Icon'
import { Notice, SelectControl } from '../../../shared/ui'
import { useToast } from '../../../shared/ui/useToast'
import '../admin-results.css'

const OVERVIEW_PAGE_SIZE = 12
const RESULT_PAGE_SIZE = 50
const REVIEWABLE_EXAM_STATES = new Set(['closed', 'cancelled'])

export function AdminResultsPage({ adminData, gateway, onNavigate }) {
  const [reviews, setReviews] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [levelId, setLevelId] = useState('all')
  const [subjectId, setSubjectId] = useState('all')
  const [decision, setDecision] = useState('pending_review')
  const [requestedPage, setPage] = useState(1)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    gateway.results.listResultReviewSets()
      .then((payload) => {
        if (!cancelled) setReviews(payload?.reviews || [])
      })
      .catch((requestError) => {
        if (!cancelled) setError(requestError.userMessage || 'Weave could not load result review sets.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [gateway])

  const reviewByExam = useMemo(() => new Map(reviews.map((review) => [review.exam_id, review])), [reviews])
  const resultSets = useMemo(() => adminData.exams
    .filter((exam) => REVIEWABLE_EXAM_STATES.has(exam.status))
    .map((exam) => ({ exam, review: reviewByExam.get(exam.id) || fallbackReview(exam) })), [adminData.exams, reviewByExam])

  const levels = useMemo(() => buildAcademicLevels(adminData.subjects), [adminData.subjects])
  const levelSubjects = useMemo(
    () => levelId === 'all' ? [] : listSubjectsForLevel(adminData.subjects, levelId),
    [adminData.subjects, levelId],
  )

  const metrics = useMemo(() => ({
    pending: resultSets.filter(({ review }) => dispositionOf(review) === 'pending_review').length,
    approved: resultSets.filter(({ review }) => dispositionOf(review) === 'approved').length,
    voided: resultSets.filter(({ review }) => dispositionOf(review) === 'voided').length,
    issues: resultSets.filter(({ review }) => Number(review.failed_count || 0) > 0).length,
  }), [resultSets])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return resultSets.filter(({ exam, review }) => {
      if (decision !== 'all' && dispositionOf(review) !== decision) return false
      if (levelId !== 'all' && exam.academicLevelId !== levelId) return false
      if (subjectId !== 'all' && exam.curriculumSubjectId !== subjectId) return false
      if (!needle) return true
      return `${exam.title} ${exam.academicLevelName} ${exam.subjectName} ${exam.assessmentName}`.toLowerCase().includes(needle)
    })
  }, [decision, levelId, query, resultSets, subjectId])

  const pageCount = Math.max(1, Math.ceil(filtered.length / OVERVIEW_PAGE_SIZE))
  const page = Math.min(requestedPage, pageCount)
  const visible = filtered.slice((page - 1) * OVERVIEW_PAGE_SIZE, page * OVERVIEW_PAGE_SIZE)

  const levelOptions = [
    { value: 'all', label: 'All levels' },
    ...levels.map((level) => ({ value: level.id, label: level.name })),
  ]
  const subjectOptions = [
    { value: 'all', label: 'All subjects' },
    ...levelSubjects.map((subject) => ({ value: subject.id, label: subject.name, description: subject.code || undefined })),
  ]
  const decisionOptions = [
    { value: 'pending_review', label: 'Pending review' },
    { value: 'all', label: 'All decisions' },
    { value: 'approved', label: 'Approved' },
    { value: 'voided', label: 'Voided' },
  ]

  const changeLevel = (nextLevel) => {
    setLevelId(nextLevel)
    setSubjectId('all')
    setPage(1)
  }

  return (
    <div className="teacher-reference-page admin-results-page">
      <div className="teacher-page-heading admin-results-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="results" size={27} /></span>
            <h1>Results</h1>
          </div>
          <p>Review completed examination result sets before approving them for synchronization to Weave.</p>
        </div>
      </div>

      {adminData.error && <Notice tone="danger">{adminData.error}</Notice>}
      {adminData.warning && <Notice tone="warning">{adminData.warning}</Notice>}
      {error && <Notice tone="danger">{error}</Notice>}

      <section className="admin-results-metrics" aria-label="Result review summary">
        <ResultMetric label="Pending review" value={metrics.pending} copy="Awaiting an administrator decision" tone="pending" />
        <ResultMetric label="Approved" value={metrics.approved} copy="Authorized for Weave synchronization" tone="approved" />
        <ResultMetric label="Voided" value={metrics.voided} copy="Kept out of academic synchronization" tone="voided" />
        <ResultMetric label="Sync issues" value={metrics.issues} copy="Approved sets with failed deliveries" tone="issue" />
      </section>

      <div className="admin-results-filters">
        <label className="teacher-search-control teacher-search-control--grow">
          <RiSearchLine size={18} aria-hidden="true" />
          <input
            aria-label="Search result sets"
            type="search"
            value={query}
            onChange={(event) => { setQuery(event.target.value); setPage(1) }}
            placeholder="Search by exam title, level, subject, or assessment..."
          />
        </label>
        <SelectControl label="Result level filter" value={levelId} options={levelOptions} onChange={changeLevel} />
        <SelectControl
          label="Result subject filter"
          value={subjectId}
          options={subjectOptions}
          onChange={(value) => { setSubjectId(value); setPage(1) }}
          disabled={levelId === 'all'}
        />
        <SelectControl label="Result decision filter" value={decision} options={decisionOptions} onChange={(value) => { setDecision(value); setPage(1) }} />
      </div>

      <section className="admin-results-table-shell" aria-label="Examination result sets" aria-busy={loading || adminData.loading}>
        <div className="admin-results-list-heading">
          <h2>Examination results</h2>
          <span>{filtered.length} result {filtered.length === 1 ? 'set' : 'sets'}</span>
        </div>
        <div className="admin-results-table-scroll" role="region" aria-label="Scrollable examination results" tabIndex={0}>
        <table className="admin-results-overview-table">
          <thead>
            <tr>
              <th>Examination</th>
              <th>Results</th>
              <th>Decision</th>
              <th>Synchronization</th>
              <th>Completed</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {!loading && visible.map(({ exam, review }) => (
              <tr key={exam.id}>
                <td>
                  <div className="admin-result-exam-cell">
                    <span><Icon name="exam" size={18} /></span>
                    <div><strong>{exam.title}</strong><small>{[exam.academicLevelName, exam.subjectName, exam.assessmentName].filter(Boolean).join(' · ')}</small></div>
                  </div>
                </td>
                <td><strong className="admin-result-count">{Number(review.result_count || 0)}</strong></td>
                <td><DecisionBadge value={dispositionOf(review)} /></td>
                <td><SyncSummary review={review} /></td>
                <td><span className="admin-result-date">{formatCompactDate(exam.closedAt || exam.cancelledAt)}</span></td>
                <td>
                  <button className="admin-results-review-link" type="button" onClick={() => onNavigate('result-detail', { selectedExamId: exam.id })}>
                    Review <RiArrowRightLine size={16} />
                  </button>
                </td>
              </tr>
            ))}
            {(loading || adminData.loading) && <tr><td colSpan={6}><div className="admin-results-table-state">Loading result review sets…</div></td></tr>}
            {!loading && !adminData.loading && visible.length === 0 && (
              <tr><td colSpan={6}><div className="admin-results-table-state"><strong>{resultSets.length ? 'No result sets match these filters' : 'No completed examination results yet'}</strong><span>{resultSets.length ? 'Adjust the decision, academic scope, or search term.' : 'Closed examinations will appear here for review.'}</span></div></td></tr>
            )}
          </tbody>
        </table>
        </div>
        <div className="admin-results-table-footer">
          <span>{filtered.length === 0 ? '0 result sets' : `Showing ${(page - 1) * OVERVIEW_PAGE_SIZE + 1}–${Math.min(page * OVERVIEW_PAGE_SIZE, filtered.length)} of ${filtered.length} result sets`}</span>
          <div>
            <button type="button" aria-label="Previous result set page" disabled={page === 1} onClick={() => setPage(page - 1)}>‹</button>
            <span>{page} / {pageCount}</span>
            <button type="button" aria-label="Next result set page" disabled={page === pageCount} onClick={() => setPage(page + 1)}>›</button>
          </div>
        </div>
      </section>
    </div>
  )
}

export function AdminResultDetailPage({ state, adminData, gateway, onNavigate }) {
  const exam = adminData.exams.find((item) => item.id === state.staff.selectedExamId)
  const [payload, setPayload] = useState(null)
  const [control, setControl] = useState(null)
  const [summary, setSummary] = useState(null)
  const [query, setQuery] = useState('')
  const [syncStatus, setSyncStatus] = useState('all')
  const [requestedPage, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [decision, setDecision] = useState(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [refreshToken, setRefreshToken] = useState(0)
  const [individualResult, setIndividualResult] = useState(null)
  const { showError } = useToast()

  const total = payload?.total || 0
  const pageCount = Math.max(1, Math.ceil(total / RESULT_PAGE_SIZE))
  const page = Math.min(requestedPage, pageCount)

  useEffect(() => {
    if (!exam) return undefined
    let cancelled = false
    Promise.all([
      gateway.results.getExamResultControl(exam.id),
      gateway.results.listResultReviewSets(),
    ]).then(([nextControl, reviewsPayload]) => {
      if (cancelled) return
      setControl(nextControl)
      setSummary((reviewsPayload?.reviews || []).find((item) => item.exam_id === exam.id) || fallbackReview(exam))
    }).catch((requestError) => {
      if (!cancelled) setError(requestError.userMessage || 'Weave could not load the result decision state.')
    })
    return () => { cancelled = true }
  }, [exam?.id, gateway, refreshToken])

  useEffect(() => {
    if (!exam) return undefined
    let cancelled = false
    const timer = window.setTimeout(async () => {
      setLoading(true)
      setError('')
      try {
        const params = { offset: (page - 1) * RESULT_PAGE_SIZE, limit: RESULT_PAGE_SIZE }
        if (query.trim()) params.search = query.trim()
        if (syncStatus !== 'all') params.sync_status = syncStatus
        const response = await gateway.results.listExamResults(exam.id, params)
        if (!cancelled) setPayload(response)
      } catch (requestError) {
        if (!cancelled) setError(requestError.userMessage || 'Weave could not load candidate results for this examination.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, query.trim() ? 220 : 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [exam?.id, gateway, page, query, refreshToken, syncStatus])

  if (!exam) {
    return (
      <div className="teacher-reference-page admin-result-detail">
        <button className="admin-results-back" type="button" onClick={() => onNavigate('results')}><RiArrowLeftLine size={17} /> Back to results</button>
        <Notice tone="warning">The selected examination is no longer available.</Notice>
      </div>
    )
  }

  const disposition = control?.result_disposition || summary?.result_disposition || (exam.status === 'cancelled' ? 'voided' : 'pending_review')
  const syncOptions = [
    { value: 'all', label: 'All sync states' },
    { value: 'pending', label: 'Pending' },
    { value: 'syncing', label: 'Syncing' },
    { value: 'synced', label: 'Synced' },
    { value: 'failed', label: 'Failed' },
  ]

  const runDecision = async () => {
    if (!decision || busy) return
    if (decision !== 'approve' && !reason.trim()) {
      setError('Enter a reason before voiding this examination result set.')
      return
    }
    setBusy(true)
    setError('')
    try {
      if (decision === 'approve') await gateway.results.approveExamResults(exam.id)
      if (decision === 'void') await gateway.results.voidExamResults(exam.id, reason.trim())
      if (decision === 'void-individual') await gateway.results.voidResult(individualResult.id, reason.trim())
      if (decision === 'restore-individual') await gateway.results.restoreResult(individualResult.id, reason.trim())
      setDecision(null)
      setIndividualResult(null)
      setReason('')
      setRefreshToken((value) => value + 1)
    } catch (requestError) {
      if (individualResult) showError(requestError.userMessage || 'Could not update this candidate result.')
      else setError(requestError.userMessage || `Weave could not ${decision} this result set.`)
    } finally {
      setBusy(false)
    }
  }

  const retrySync = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await gateway.results.retryExamResultSync(exam.id)
      setRefreshToken((value) => value + 1)
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not retry failed result synchronization.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="teacher-reference-page admin-result-detail">
      <button className="admin-results-back" type="button" onClick={() => onNavigate('results')}><RiArrowLeftLine size={17} /> Back to results</button>

      <div className="teacher-page-heading admin-result-detail__heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="results" size={27} /></span>
            <h1>{exam.title}</h1>
          </div>
          <p>{[exam.academicLevelName, exam.subjectName, exam.assessmentName].filter(Boolean).join(' · ')}</p>
        </div>
        <DecisionBadge value={disposition} />
      </div>

      {error && <Notice tone="danger">{error}</Notice>}

      <section className="admin-result-summary" aria-label="Result set summary">
        <ResultSummaryItem label="Candidate results" value={String(summary?.result_count ?? total)} hint={summary?.voided_count ? `${summary.voided_count} individually voided` : 'Calculated local results'} />
        <ResultSummaryItem label="Component maximum" value={formatNumber(exam.componentMaximumScore)} hint={exam.assessmentName || 'Assessment component'} />
        <ResultSummaryItem label="Decision" value={decisionLabel(disposition)} hint={control?.results_decided_at ? `Decided ${formatCompactDate(control.results_decided_at)}` : 'Awaiting administrator review'} />
        <ResultSummaryItem label="Completed" value={formatCompactDate(exam.closedAt || exam.cancelledAt)} hint={exam.status === 'cancelled' ? 'Sitting cancelled' : 'Examination closed'} />
      </section>

      <ResultDecisionPanel
        disposition={disposition}
        summary={summary}
        reason={control?.results_decision_reason}
        busy={busy}
        onApprove={() => setDecision('approve')}
        onVoid={() => setDecision('void')}
        onRetry={retrySync}
      />

      <div className="admin-result-detail__filters">
        <label className="teacher-search-control teacher-search-control--grow">
          <RiSearchLine size={18} aria-hidden="true" />
          <input
            aria-label="Search candidate results"
            type="search"
            value={query}
            onChange={(event) => { setQuery(event.target.value); setPage(1) }}
            placeholder="Search candidate name or admission number..."
          />
        </label>
        <SelectControl label="Result sync status filter" value={syncStatus} options={syncOptions} onChange={(value) => { setSyncStatus(value); setPage(1) }} />
      </div>

      <section className="admin-results-table-shell" aria-label={`Candidate results for ${exam.title}`} aria-busy={loading}>
        <div className="admin-results-table-scroll" role="region" aria-label="Scrollable candidate results" tabIndex={0}>
        <table className="admin-results-candidate-table">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Raw score</th>
              <th>Component score</th>
              <th>Sync</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {!loading && (payload?.results || []).map((result) => (
              <tr key={result.id}>
                <td><div className="admin-result-candidate"><span>{initials(result.candidate_display_name)}</span><div><strong>{result.candidate_display_name}</strong><small className="admin-result-admission">{result.admission_number}</small></div></div></td>
                <td><strong>{result.raw_score} / {result.raw_max_score}</strong><small className="admin-result-score-percentage">{formatNumber(result.percentage)}%</small></td>
                <td><strong>{formatNumber(result.component_score)} / {formatNumber(result.component_maximum_score)}</strong></td>
                <td>{result.voided_at ? <span className="admin-result-void-audit"><DecisionBadge value="voided" /><small>{result.void_reason}</small><small>{formatCompactDate(result.voided_at)}</small></span> : <SyncBadge value={result.sync_status} error={result.sync_error} />}</td>
                <td>{!result.voided_at && disposition !== 'voided' && (
                  <button type="button" className="admin-result-button admin-result-button--secondary" disabled={busy || !control || Boolean(control.operation) || Boolean(result.sync_batch_id) || !['pending', 'failed'].includes(result.sync_status)} title={result.sync_batch_id || ['syncing', 'synced'].includes(result.sync_status) ? 'Synchronization has started. Resolve this result in Weave.' : 'Void this candidate’s result only'} onClick={() => { setIndividualResult(result); setReason(''); setDecision('void-individual') }}>Void result</button>
                )}{result.voided_at && disposition !== 'voided' && <button type="button" className="admin-result-button admin-result-button--secondary" disabled={busy || !control || Boolean(control.operation)} onClick={() => { setIndividualResult(result); setReason(''); setDecision('restore-individual') }}>Undo void</button>}</td>
              </tr>
            ))}
            {loading && <tr><td colSpan={5}><div className="admin-results-table-state">Loading candidate results…</div></td></tr>}
            {!loading && !error && (payload?.results || []).length === 0 && (
              <tr><td colSpan={5}><div className="admin-results-table-state"><strong>No candidate results match these filters</strong><span>Try another admission number, candidate name, or sync state.</span></div></td></tr>
            )}
          </tbody>
        </table>
        </div>
        <div className="admin-results-table-footer">
          <span>{total ? `Showing ${(page - 1) * RESULT_PAGE_SIZE + 1}–${Math.min(page * RESULT_PAGE_SIZE, total)} of ${total} results` : '0 results'}</span>
          <div>
            <button type="button" aria-label="Previous result page" disabled={page === 1 || loading} onClick={() => setPage(page - 1)}>‹</button>
            <span>{page} / {pageCount}</span>
            <button type="button" aria-label="Next result page" disabled={page === pageCount || loading} onClick={() => setPage(page + 1)}>›</button>
          </div>
        </div>
      </section>

      {decision && (
        <ResultDecisionModal
          action={decision}
          result={['void-individual', 'restore-individual'].includes(decision) ? individualResult : null}
          exam={exam}
          count={summary?.result_count ?? total}
          reason={reason}
          setReason={setReason}
          busy={busy}
          onCancel={() => { if (!busy) { setDecision(null); setIndividualResult(null); setReason(''); setError('') } }}
          onConfirm={runDecision}
        />
      )}
    </div>
  )
}

function ResultMetric({ label, value, copy, tone }) {
  const MetricIcon = tone === 'pending' ? RiTimeLine : tone === 'approved' ? RiCheckLine : tone === 'voided' ? RiCloseCircleLine : RiRefreshLine
  return (
    <article className={`admin-result-metric${tone ? ` admin-result-metric--${tone}` : ''}`}>
      <span>{label}</span>
      <div className="admin-result-metric__icon"><MetricIcon size={21} aria-hidden="true" /></div>
      <strong>{value}</strong>
      <small>{copy}</small>
    </article>
  )
}

function ResultSummaryItem({ label, value, hint }) {
  return <article className="admin-result-summary__item"><span>{label}</span><strong>{value || '—'}</strong><small>{hint}</small></article>
}

function ResultDecisionPanel({ disposition, summary, reason, busy, onApprove, onVoid, onRetry }) {
  const failed = Number(summary?.failed_count || 0)
  if (disposition === 'pending_review') {
    return (
      <section className="admin-result-decision-panel admin-result-decision-panel--pending">
        <div className="admin-result-decision-panel__icon"><Icon name="audit" size={22} /></div>
        <div className="admin-result-decision-panel__copy">
          <strong>Administrator decision required</strong>
          <p>These scores remain local to this CBT server until you approve the entire examination result set. Void only if this sitting must not contribute academic results.</p>
        </div>
        <div className="admin-result-decision-panel__actions">
          <button type="button" className="admin-result-button admin-result-button--danger-quiet" disabled={busy} onClick={onVoid}><RiCloseCircleLine size={17} /> Void result set</button>
          <button type="button" className="admin-result-button admin-result-button--primary" disabled={busy} onClick={onApprove}><RiCheckLine size={17} /> Approve results</button>
        </div>
      </section>
    )
  }
  if (disposition === 'approved') {
    return (
      <section className="admin-result-decision-panel admin-result-decision-panel--approved">
        <div className="admin-result-decision-panel__icon"><RiCheckLine size={22} /></div>
        <div className="admin-result-decision-panel__copy">
          <strong>{failed ? 'Weave synchronization needs attention' : 'Approved for Weave synchronization'}</strong>
          <p>{failed ? `${failed} result${failed === 1 ? ' has' : 's have'} not reached Weave. Read the failure reason in the candidate results below. Correct the issue in Weave before retrying; temporary delivery failures retry automatically.` : 'The result set has passed the local approval boundary. Synchronization status is shown per candidate below.'}</p>
        </div>
        {failed > 0 && <button type="button" className="admin-result-button admin-result-button--secondary" disabled={busy} onClick={onRetry}><RiRefreshLine size={17} /> Retry failed sync</button>}
      </section>
    )
  }
  return (
    <section className="admin-result-decision-panel admin-result-decision-panel--voided">
      <div className="admin-result-decision-panel__icon"><RiCloseCircleLine size={22} /></div>
      <div className="admin-result-decision-panel__copy">
        <strong>Result set voided</strong>
        <p>{reason || 'These examination results are not authorized for synchronization to Weave.'}</p>
      </div>
    </section>
  )
}

function ResultDecisionModal({ action, exam, result, count, reason, setReason, busy, onCancel, onConfirm }) {
  const approving = action === 'approve'
  const restoring = action === 'restore-individual'
  const positive = approving || restoring
  return createPortal(
    <div className="admin-result-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onCancel() }}>
      <section className={`admin-result-modal${positive ? '' : ' is-danger'}`} role="alertdialog" aria-modal="true" aria-labelledby="result-decision-title">
        <div className="admin-result-modal__heading">
          <span>{positive ? <RiCheckLine size={22} /> : <RiCloseCircleLine size={22} />}</span>
          <div>
            <h2 id="result-decision-title">{approving ? 'Approve this result set?' : restoring ? 'Undo this candidate’s result void?' : result ? 'Void this candidate result?' : 'Void this result set?'}</h2>
            <p>{approving ? 'Approval authorizes these local CBT scores for synchronization to Weave.' : restoring ? 'This restores the recorded score. Both decisions remain in the audit history.' : result ? 'This score will be excluded from synchronization. The score and reason remain on record.' : 'Voiding prevents this examination sitting from contributing valid academic results.'}</p>
          </div>
        </div>
        <div className="admin-result-modal__exam"><span>{result ? 'Candidate' : 'Examination'}</span><strong>{result ? result.candidate_display_name : exam.title}</strong><small>{result ? `${result.admission_number} · ${exam.title}` : `${count} candidate result${count === 1 ? '' : 's'} · ${[exam.academicLevelName, exam.subjectName, exam.assessmentName].filter(Boolean).join(' · ')}`}</small></div>
        {!approving && (
          <label className="admin-result-modal__reason">
            <span>{restoring ? 'Reason for restoring' : 'Reason for voiding'}</span>
            <textarea rows="4" maxLength={1024} disabled={busy} value={reason} onChange={(event) => setReason(event.target.value)} placeholder={restoring ? 'Explain why this candidate result should be restored...' : result ? 'Explain why this candidate result must be voided...' : 'Explain why this entire examination result set must be voided...'} />
          </label>
        )}
        <div className={`admin-result-modal__warning${positive ? '' : ' is-danger'}`}>
          {approving
            ? 'Once synchronization begins, this result set can no longer be voided through the local review workflow.'
            : restoring ? 'Pending restored scores synchronize automatically once this exam result set is approved. Previously failed scores still require correcting the reported issue and using Retry failed sync.' : result ? 'Only this candidate’s result will be voided. Other candidate results remain eligible for approval and synchronization.' : 'This decision applies to the entire examination result set, not a single candidate.'}
        </div>
        <div className="admin-result-modal__actions">
          <button type="button" className="admin-result-button admin-result-button--secondary" disabled={busy} onClick={onCancel}>Cancel</button>
          <button type="button" className={`admin-result-button ${positive ? 'admin-result-button--primary' : 'admin-result-button--danger'}`} disabled={busy || (Boolean(result) && !reason.trim())} onClick={onConfirm}>
            {busy ? 'Working…' : approving ? 'Approve results' : restoring ? 'Restore candidate result' : result ? 'Void candidate result' : 'Void result set'}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  )
}

function DecisionBadge({ value }) {
  const normalized = value || 'pending_review'
  return <span className={`admin-result-decision admin-result-decision--${normalized}`}>{decisionLabel(normalized)}</span>
}

function SyncBadge({ value, error }) {
  const normalized = value || 'pending'
  return (
    <div className="admin-result-sync-detail">
      <span className={`admin-result-sync admin-result-sync--${normalized}`}>{titleCase(normalized)}</span>
      {normalized === 'failed' && (
        <div className="admin-result-sync-detail__error">
          <strong>Why synchronization failed</strong>
          <p>{error || 'No failure reason was recorded. Ask the administrator to check the worker logs before retrying.'}</p>
          {error?.startsWith('TEACHER_ASSIGNMENT_NOT_FOUND:') && (
            <p>In Weave, assign a teacher to this candidate?s class and exam subject, with effective dates covering the exam date. Then retry failed sync.</p>
          )}
        </div>
      )}
    </div>
  )
}

function SyncSummary({ review }) {
  const total = Math.max(0, Number(review.result_count || 0) - Number(review.voided_count || 0))
  const failed = Number(review.failed_count || 0)
  const syncing = Number(review.syncing_count || 0)
  const synced = Number(review.synced_count || 0)
  if (review.result_count > 0 && total === 0) return <span className="admin-result-sync-summary is-voided"><strong>Not sent</strong><small>All candidate results voided</small></span>
  if (failed) return <span className="admin-result-sync-summary is-failed"><strong>{failed} failed</strong><small>{synced} of {total} synced</small></span>
  if (syncing) return <span className="admin-result-sync-summary is-syncing"><strong>Syncing</strong><small>{synced} of {total} synced</small></span>
  if (total > 0 && synced === total) return <span className="admin-result-sync-summary is-synced"><strong>Synced</strong><small>{total} delivered</small></span>
  if (dispositionOf(review) === 'voided') return <span className="admin-result-sync-summary is-voided"><strong>Not sent</strong><small>Result set voided</small></span>
  return <span className="admin-result-sync-summary"><strong>Not started</strong><small>{total} local result{total === 1 ? '' : 's'}</small></span>
}

function fallbackReview(exam) {
  return {
    exam_id: exam.id,
    result_disposition: exam.status === 'cancelled' ? 'voided' : 'pending_review',
    result_count: 0,
    pending_count: 0,
    syncing_count: 0,
    synced_count: 0,
    failed_count: 0,
  }
}

function dispositionOf(review) { return review?.result_disposition || 'pending_review' }
function decisionLabel(value) { return value === 'approved' ? 'Approved' : value === 'voided' ? 'Voided' : 'Pending review' }
function titleCase(value) { return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) }
function initials(value) { return String(value || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || '?' }
function formatNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
}
function formatCompactDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date)
}
