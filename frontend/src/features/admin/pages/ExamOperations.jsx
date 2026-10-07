import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  RiArrowLeftLine,
  RiCalendarScheduleLine,
  RiCheckboxCircleLine,
  RiErrorWarningLine,
  RiCloseCircleLine,
  RiPauseCircleLine,
  RiPlayCircleLine,
  RiSearchLine,
  RiStopCircleLine,
} from '@remixicon/react'
import { buildAcademicLevels, listSubjectsForLevel } from '../../../shared/academics/authoringScope'
import { Icon } from '../../../shared/icons/Icon'
import { Notice, SelectControl } from '../../../shared/ui'
import { useOperationsMonitor } from '../useOperationsMonitor'
import '../admin-exam-operations.css'
import { AdminDatePicker } from '../AdminDatePicker'
import { OperationsQuickActions } from '../OperationsQuickActions'
import { ActivationReviewModal } from '../components/ActivationReviewModal'
import { BulkExamOperations } from '../components/BulkExamOperations'

const OPERATIONAL_STATUSES = new Set(['sealed', 'active', 'suspended', 'closing', 'cancelling', 'closed', 'cancelled'])
const LIVE_STATUSES = new Set(['active', 'suspended', 'closing', 'cancelling'])
const TERMINAL_STATUSES = new Set(['closed', 'cancelled'])
const POLLABLE_STATUSES = new Set(['sealed', 'active', 'suspended', 'closing', 'cancelling'])
const TABS = [
  ['today', 'Today'],
  ['ready', 'Ready'],
  ['live', 'Live'],
  ['upcoming', 'Upcoming'],
  ['completed', 'Completed'],
  ['all', 'All'],
]

export function ExamOperations({ adminData, gateway, onNavigate }) {
  const [tab, setTab] = useState('today')
  const [query, setQuery] = useState('')
  const [levelId, setLevelId] = useState('all')
  const [subjectId, setSubjectId] = useState('all')
  const [day, setDay] = useState(() => localDay(new Date()))
  const [selectedLiveId, setSelectedLiveId] = useState('')
  const refreshExams = adminData.refreshExams
  const operationalExams = adminData.exams.filter((exam) => OPERATIONAL_STATUSES.has(exam.status))
  const levels = buildAcademicLevels(adminData.subjects)
  const levelSubjects = levelId === 'all' ? [] : listSubjectsForLevel(adminData.subjects, levelId)
  const date = new Date(`${day}T12:00:00`)
  const isToday = day === localDay(new Date())
  const needle = query.trim().toLowerCase()
  const scoped = operationalExams.filter((exam) =>
    isScheduledToday(exam, date)
    && (levelId === 'all' || exam.academicLevelId === levelId)
    && (subjectId === 'all' || exam.curriculumSubjectId === subjectId)
    && (!needle || `${exam.title} ${exam.academicLevelName} ${exam.subjectName} ${exam.assessmentName}`.toLowerCase().includes(needle)),
  )
  const scheduled = scoped
  const live = scoped.filter((exam) => LIVE_STATUSES.has(exam.status)).sort(compareOperationalExams)
  const ready = scheduled.filter((exam) => exam.status === 'sealed' && exam.rosterStatus === 'ready')
  const attention = scoped.filter(needsAttention)
  const selectedLive = live.find((exam) => exam.id === selectedLiveId) || live[0]
  const monitor = useOperationsMonitor(selectedLive?.id, gateway?.exams?.listExamAttempts)
  const connectionIssues = monitor.error ? [] : monitor.attempts.filter((attempt) => ['recently_disconnected', 'stale'].includes(attempt.connectivity))
  const timeline = scoped.filter((exam) => matchesTab(exam, tab)).sort((a, b) =>
    (Date.parse(a.scheduledStartAt) || Number.MAX_SAFE_INTEGER) - (Date.parse(b.scheduledStartAt) || Number.MAX_SAFE_INTEGER),
  )
  const counts = Object.fromEntries(TABS.map(([key]) => [key, scoped.filter((exam) => matchesTab(exam, key)).length]))
  const events = scoped.flatMap((exam) => [
    ['activatedAt', 'Examination activated', 'bolt'],
    ['closedAt', 'Examination closed', 'check'],
    ['cancelledAt', 'Sitting cancelled', 'flag'],
    ['rosterPreparedAt', 'Candidate roster prepared', 'roster'],
  ].flatMap(([field, label, icon]) => exam[field] && localDay(new Date(exam[field])) === day
    ? [{ id: `${exam.id}-${field}`, exam, label, icon, at: exam[field] }] : []))
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at)).slice(0, 6)
  const openExam = (exam) => onNavigate('operation-detail', { selectedExamId: exam.id })

  // Poll even an empty day so newly sealed/activated exams appear without navigation.
  useEffect(() => {
    let stopped = false
    let timer
    const poll = async () => {
      try {
        if (document.visibilityState === 'visible') await refreshExams({ silent: true })
      } finally {
        if (!stopped) timer = window.setTimeout(poll, 10000)
      }
    }
    timer = window.setTimeout(poll, 10000)
    return () => { stopped = true; window.clearTimeout(timer) }
  }, [refreshExams])

  return (
    <div className="teacher-reference-page admin-ops-page">
      <div className="teacher-page-heading admin-ops-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="operations" size={23} /></span>
            <h1>Exam Operations</h1>
          </div>
          <p>Your exam-day overview. Monitor sittings, spot issues and keep candidates moving.</p>
        </div>
        <div className="admin-ops-toolbar">
          <AdminDatePicker value={day} onChange={setDay} />
          <OperationsQuickActions onNavigate={onNavigate} />
        </div>
      </div>
      {adminData.error && <div role="alert" className="admin-ops-inline-warning">{adminData.error} Displayed data may be out of date.</div>}
      {adminData.warning && <Notice tone="warning">{adminData.warning}</Notice>}

      <section className="admin-ops-metrics" aria-label="Examination operations summary" aria-busy={adminData.loading}>
        <OperationsMetric icon={RiCalendarScheduleLine} label={isToday ? 'Scheduled today' : 'Scheduled sittings'} value={adminData.loading ? '\u2014' : scheduled.length} helper="On the selected day's schedule" />
        <OperationsMetric icon={RiCheckboxCircleLine} label="Ready to start" value={adminData.loading ? '\u2014' : ready.length} helper="Scheduled with a ready roster" tone="ready" />
        <OperationsMetric icon={RiPlayCircleLine} label="Live examinations" value={adminData.loading ? '\u2014' : live.filter((exam) => exam.status === 'active').length} helper="Active on the selected schedule" />
        <OperationsMetric icon={RiErrorWarningLine} label="Need attention" value={adminData.loading ? '\u2014' : attention.length} helper="Suspended or roster issues" tone={attention.length ? 'attention' : ''} />
      </section>

      <div className="admin-ops-dashboard-grid">
        <section className="admin-ops-panel admin-ops-timeline" aria-label="Operations timeline" aria-busy={adminData.loading}>
          <PanelHeading icon="calendar" title={isToday ? "Today's operations timeline" : 'Operations timeline'} badge={adminData.loading ? 'Loading...' : `${timeline.length} sittings`} />
          <div className="admin-ops-filters">
            <label className="admin-ops-filter"><span>Search examinations</span><span className="teacher-search-control teacher-search-control--grow"><RiSearchLine size={18} aria-hidden="true" /><input aria-label="Search operational examinations" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find an exam, subject or level..." /></span></label>
            <div className="admin-ops-filter"><span>Academic level</span><SelectControl label="Operations level filter" value={levelId} options={[{ value: 'all', label: 'All levels' }, ...levels.map((level) => ({ value: level.id, label: level.name }))]} onChange={(value) => { setLevelId(value); setSubjectId('all') }} /></div>
            <div className="admin-ops-filter"><span>Subject</span><SelectControl label="Operations subject filter" value={subjectId} options={[{ value: 'all', label: 'All subjects' }, ...levelSubjects.map((subject) => ({ value: subject.id, label: subject.name }))]} onChange={setSubjectId} disabled={levelId === 'all'} /></div>
          </div>
          <nav className="admin-ops-view-tabs" aria-label="Operation views">{TABS.map(([key, label]) => <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(key)}>{key === 'today' && !isToday ? 'Selected day' : label}{' '}<span>{counts[key]}</span></button>)}</nav>
          <BulkExamOperations exams={timeline} scopeKey={JSON.stringify([day, tab, query, levelId, subjectId])} gateway={gateway} onRefresh={refreshExams} onOpen={openExam} disabled={adminData.loading || Boolean(adminData.error)}>
          {({ operation, selectedIds, canSelect, toggle, busy }) => <div className="admin-ops-timeline__list">
            {timeline.map((exam) => <OperationalExamRow key={exam.id} exam={exam} onOpen={() => openExam(exam)} selection={operation ? { selected: selectedIds.has(exam.id), disabled: busy || !canSelect(exam), toggle: () => toggle(exam) } : null} />)}
            {!timeline.length && <PanelEmpty icon="calendar" title={adminData.loading ? 'Loading the schedule...' : 'No examinations in this view'} copy={adminData.loading ? 'Fetching examination state.' : 'Change the date or filters to find another sitting.'} />}
          </div>}
          </BulkExamOperations>
        </section>

        <section className="admin-ops-panel admin-ops-live" aria-label="Live exam status">
          <PanelHeading icon="operations" title="Live exam status" badge={`${live.length} ongoing`} />
          {selectedLive ? <>
            {live.length > 1 && <div className="admin-ops-live-picker"><SelectControl label="Monitor examination" value={selectedLive.id} options={live.map((exam) => ({ value: exam.id, label: exam.title }))} onChange={setSelectedLiveId} /></div>}
            <LiveSitting key={selectedLive.id} exam={selectedLive} monitor={monitor} onOpen={() => openExam(selectedLive)} onRoster={() => onNavigate('roster-detail', { selectedExamId: selectedLive.id })} />
          </> : <PanelEmpty icon="operations" title={adminData.loading ? 'Loading live sittings...' : 'No live examinations'} copy="Once a sitting is activated, candidate activity and connection status appear here." />}
        </section>
        <section className="admin-ops-panel admin-ops-attention" aria-label="Attention queue">
          <PanelHeading icon="flag" title="Attention queue" badge={`${attention.length + (connectionIssues.length ? 1 : 0)} issues`} />
          <div className="admin-ops-queue">
            {connectionIssues.length > 0 && <QueueItem icon="operations" title={`${connectionIssues.length} ${connectionIssues.length === 1 ? 'candidate needs' : 'candidates need'} a connection check`} copy={`${selectedLive.title} · Based on recent heartbeats`} onClick={() => onNavigate('roster-detail', { selectedExamId: selectedLive.id })} />}
            {attention.map((exam) => <QueueItem key={exam.id} icon={exam.status === 'suspended' ? 'clock' : 'flag'} title={attentionLabel(exam)} copy={exam.title} onClick={() => exam.rosterStatus === 'failed' || exam.rosterStatus === 'stale' ? onNavigate('roster-detail', { selectedExamId: exam.id }) : openExam(exam)} />)}
            {!attention.length && !connectionIssues.length && <PanelEmpty icon="shield" title={adminData.loading ? 'Checking examination state...' : 'No exam-state issues'} copy="Suspensions, cancellations and roster problems appear here when they need attention." />}
          </div>
          <div className="admin-ops-panel-foot">Connection checks cover the selected live sitting.{monitor.error ? ' Candidate monitoring is unavailable.' : ''}</div>
        </section>
        <section className="admin-ops-panel admin-ops-ready" aria-label="Ready sittings">
          <PanelHeading icon="bolt" title="Launch readiness" badge={`${ready.length} ready`} />
          {ready.length ? <div className="admin-ops-ready-list">{ready.map((exam) => <div key={exam.id}><div><strong>{exam.title}</strong><small>{formatClock(exam.scheduledStartAt)} · {exam.rosterCandidateCount || 0} candidates</small></div><button type="button" className="admin-ops-button admin-ops-button--primary" onClick={() => openExam(exam)}>Open controls<Icon name="chevronRight" size={15} /></button></div>)}</div> : <PanelEmpty icon="check" title="No sittings ready to launch" copy="Sealed exams scheduled for this day appear here when their rosters are ready." />}
        </section>
        <section className="admin-ops-panel admin-ops-events" aria-label="Recent exam milestones">
          <details>
            <summary><Icon name="fileText" size={20} /><strong>Recent milestones</strong><span>{events.length} recorded</span><Icon name="chevronDown" size={18} /></summary>
            {events.length ? <ol className="admin-ops-event-list">{events.map((event) => <li key={event.id}><span><Icon name={event.icon} size={16} /></span><time dateTime={event.at}>{formatClock(event.at)}</time><div><strong>{event.label}</strong><button type="button" onClick={() => openExam(event.exam)}>{event.exam.title}</button></div></li>)}</ol> : <PanelEmpty icon="clock" title="No recorded milestones" copy="Roster preparation, activation and completion times will appear here." />}
          </details>
        </section>
      </div>
    </div>
  )
}

function PanelHeading({ icon, title, badge }) {
  return <header className="admin-ops-panel-heading"><h2><Icon name={icon} size={18} />{title}</h2>{badge && <span>{badge}</span>}</header>
}

function OperationsMetric({ icon: MetricIcon, label, value, helper, tone = '' }) {
  return <article className={`admin-ops-metric${tone ? ` admin-ops-metric--${tone}` : ''}`}>
    <span className="admin-ops-metric__icon"><MetricIcon size={18} aria-hidden="true" /></span>
    <div><span>{label}</span><strong>{value}</strong><small>{helper}</small></div>
  </article>
}

function PanelEmpty({ icon, title, copy }) {
  return <div className="admin-ops-panel-empty"><span><Icon name={icon} size={25} /></span><strong>{title}</strong><p>{copy}</p></div>
}

function QueueItem({ icon, title, copy, onClick }) {
  return <div className="admin-ops-queue-item"><span><Icon name={icon} size={20} /></span><div><strong>{title}</strong><small>{copy}</small></div><button type="button" className="admin-ops-button" onClick={onClick}>Review</button></div>
}


function attentionLabel(exam) {
  if (exam.rosterStatus === 'failed') return 'Roster preparation failed'
  if (exam.rosterStatus === 'stale') return 'Roster reconciliation required'
  if (exam.status === 'suspended') return 'Examination is suspended'
  return 'Cancellation in progress'
}

function localDay(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function LiveSitting({ exam, monitor, onOpen, onRoster }) {
  const [page, setPage] = useState(0)
  const available = Boolean(monitor.updatedAt)
  const attempts = monitor.attempts
  const online = attempts.filter((attempt) => attempt.connectivity === 'online').length
  const submitted = attempts.filter((attempt) => attempt.status === 'submitted').length
  const interrupted = attempts.filter((attempt) => attempt.status === 'interrupted').length
  const terminated = attempts.filter((attempt) => attempt.status === 'terminated').length
  const rosterCount = exam.rosterCandidateCount || 0
  const progress = rosterCount ? Math.min(100, Math.round(submitted / rosterCount * 100)) : 0
  const sorted = [...attempts].sort((a, b) => Number(attemptNeedsAttention(b)) - Number(attemptNeedsAttention(a)))
  const maxPage = Math.max(0, Math.ceil(sorted.length / 5) - 1)
  const currentPage = Math.min(page, maxPage)
  return <div className="admin-ops-live-body">
    <div className="admin-ops-live-identity"><div><h3>{exam.title}</h3><p>{[exam.academicLevelName, exam.subjectName].filter(Boolean).join(' \u00b7 ')}</p></div><ExamState status={exam.status} /></div>
    <div className="admin-ops-live-schedule"><Icon name="clock" size={15} />{exam.durationMinutes || 0} min · Scheduled {formatSchedule(exam.scheduledStartAt)}</div>
    {monitor.error && <div role="alert" className="admin-ops-inline-warning">{monitor.error}{available && ' Showing last known counts.'}</div>}
    {!available && <p className="admin-ops-monitor-status" role="status">{monitor.loading ? 'Loading candidate activity...' : 'Candidate activity is unavailable.'}</p>}
    <div className="admin-ops-live-counts"><div><strong>{available ? online : '\u2014'}<small> / {rosterCount}</small></strong><span>Online / roster</span></div><div><strong>{available ? submitted : '\u2014'}</strong><span>Submitted</span></div><div><strong>{available ? interrupted : '\u2014'}</strong><span>Interrupted</span></div></div>
    {available && <><div className="admin-ops-progress-label"><span>Submissions received</span><strong>{progress}%</strong></div><progress className="admin-ops-progress" max="100" value={progress} aria-label="Roster submission progress" /><p className="admin-ops-monitor-status">{attempts.length} attempts started {"\u00b7"} {terminated} terminated</p></>}
    <details className="admin-ops-candidate-details">
      <summary><span>Candidate activity</span><Icon name="chevronDown" size={16} /></summary>
      <div className="admin-ops-candidate-heading"><span>{available ? `${attempts.length} attempts started` : 'Candidate monitoring'}</span><button type="button" onClick={onRoster}>Open roster <Icon name="chevronRight" size={14} /></button></div>
      {available && !attempts.length && <p className="admin-ops-monitor-status">No candidates have started this sitting yet.</p>}
      <ul className="admin-ops-candidates">{sorted.slice(currentPage * 5, currentPage * 5 + 5).map((attempt) => <li key={attempt.id}><div><strong>{attempt.candidate_name || attempt.admission_number}</strong><small>{attempt.admission_number} · {titleCase(attempt.status)}</small></div><span className={attemptNeedsAttention(attempt) ? 'is-attention' : ''}>{attempt.connectivity === 'terminal' ? titleCase(attempt.status) : titleCase(attempt.connectivity)}<small>{attempt.connectivity !== 'terminal' ? `Seen ${Math.floor(attempt.heartbeat_age_seconds / 60)}m ago` : attempt.end_reason ? titleCase(attempt.end_reason) : 'Attempt ended'}</small></span></li>)}</ul>
      {sorted.length > 5 && <div className="admin-ops-pagination"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button><span>{currentPage + 1} / {maxPage + 1}</span><button type="button" disabled={currentPage === maxPage} onClick={() => setPage(currentPage + 1)}>Next</button></div>}
    </details>
    <button type="button" className="admin-ops-button admin-ops-button--primary admin-ops-live-control" onClick={onOpen}>Open control room<Icon name="chevronRight" size={16} /></button>
    <p className="admin-ops-monitor-status">{available ? `Last candidate update ${formatClock(monitor.updatedAt)}` : 'Waiting for candidate monitoring'} · Refreshes every 10s</p>
  </div>
}

function attemptNeedsAttention(attempt) {
  return attempt.status === 'interrupted' || ['recently_disconnected', 'stale'].includes(attempt.connectivity)
}

export function ExamOperationsDetail({ state, adminData, gateway, onNavigate }) {
  const exam = adminData.exams.find((item) => item.id === state.staff.selectedExamId)
  const examId = exam?.id
  const examStatus = exam?.status
  const [pendingAction, setPendingAction] = useState(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const refreshExams = adminData.refreshExams

  useEffect(() => {
    if (!examId || !POLLABLE_STATUSES.has(examStatus)) return undefined
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refreshExams({ silent: true })
    }, 4000)
    return () => window.clearInterval(timer)
  }, [examId, examStatus, refreshExams])

  if (!exam) {
    return (
      <div className="teacher-reference-page admin-ops-detail">
        <button className="admin-ops-back" type="button" onClick={() => onNavigate('operations')}><RiArrowLeftLine size={17} /> Back to operations</button>
        <Notice tone="warning">The selected examination is no longer available.</Notice>
      </div>
    )
  }

  const controls = controlsFor(exam)
  const openAction = (action) => {
    setPendingAction(action)
    setReason('')
    setError('')
  }
  const closeModal = () => {
    if (busy) return
    setPendingAction(null)
    setReason('')
    setError('')
  }
  const confirmAction = async () => {
    if (!pendingAction) return
    if (requiresReason(pendingAction) && !reason.trim()) {
      setError('Enter a reason before continuing with this examination action.')
      return
    }
    setBusy(true)
    setError('')
    try {
      if (pendingAction === 'suspend') await gateway.exams.suspendExam(exam.id, reason.trim())
      if (pendingAction === 'resume') await gateway.exams.resumeExam(exam.id, reason.trim() || undefined)
      if (pendingAction === 'close') await gateway.exams.closeExam(exam.id)
      if (pendingAction === 'cancel') await gateway.exams.cancelExam(exam.id, reason.trim())
      await refreshExams({ silent: false })
      setPendingAction(null)
      setReason('')
    } catch (requestError) {
      setError(requestError.userMessage || `Weave could not ${pendingAction} this examination.`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="teacher-reference-page admin-ops-detail">
      <button className="admin-ops-back" type="button" onClick={() => onNavigate('operations')}><RiArrowLeftLine size={17} /> Back to operations</button>

      <div className="admin-ops-detail__hero">
        <div className="admin-ops-detail__identity">
          <span className="admin-ops-detail__icon"><Icon name="operations" size={23} /></span>
          <div>
            <div className="admin-ops-detail__eyebrow">{[exam.academicLevelName, exam.subjectName, exam.assessmentName].filter(Boolean).join(' · ')}</div>
            <h1>{exam.title}</h1>
            <p>{scheduleSentence(exam)}</p>
          </div>
        </div>
        <ExamState status={exam.status} />
      </div>

      {operationNotice(exam)}
      {adminData.error && <Notice tone="danger">{adminData.error}</Notice>}

      <section className="admin-ops-detail__metrics" aria-label="Examination control summary">
        <DetailMetric label="Scheduled start" value={formatSchedule(exam.scheduledStartAt)} helper={exam.latestNormalStartAt ? `Normal entry until ${formatClock(exam.latestNormalStartAt)}` : 'No normal-entry cutoff supplied'} />
        <DetailMetric label="Candidate roster" value={String(exam.rosterCandidateCount || 0)} helper={`Roster ${rosterLabel(exam.rosterStatus).toLowerCase()} · v${exam.rosterVersion || 0}`} />
        <DetailMetric label="Duration" value={`${exam.durationMinutes || 0} min`} helper={`${exam.questionCount || 0} questions in the sealed paper`} />
      </section>

      <div className="admin-ops-detail__grid">
        <section className="admin-ops-control-panel" aria-labelledby="admin-ops-controls-title">
          <div className="admin-ops-section-heading">
            <div><span>Manage this sitting</span><h2 id="admin-ops-controls-title">Exam controls</h2></div>
          </div>

          <div className="admin-ops-control-panel__body">
            <div className="admin-ops-control-copy">
              <span className="admin-ops-control-copy__icon"><ControlStateIcon status={exam.status} /></span>
              <div>
                <strong>{controlMessage(exam)}</strong>
                <p>{controlDescription(exam)}</p>
              </div>
            </div>

            {controls.length > 0 ? (
              <div className="admin-ops-actions">
                {controls.map((control) => {
                  const ActionIcon = control.Icon
                  return (
                    <button
                      key={control.action}
                      type="button"
                      className={`admin-ops-action admin-ops-action--${control.tone || 'neutral'}`}
                      disabled={control.disabled}
                      onClick={() => openAction(control.action)}
                    >
                      <span><ActionIcon size={19} /></span>
                      <div><strong>{control.label}</strong><small>{control.copy}</small></div>
                      <Icon name="chevronRight" size={20} />
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="admin-ops-readonly"><Icon name="info" size={18} /><span>{terminalControlCopy(exam.status)}</span></div>
            )}
          </div>
        </section>

        <aside className="admin-ops-context-panel">
          <div className="admin-ops-section-heading"><div><span>Related information</span><h2>Exam resources</h2></div></div>
          <button type="button" onClick={() => onNavigate('roster-detail', { selectedExamId: exam.id })}>
            <span><Icon name="roster" size={19} /></span>
            <div><strong>Candidate roster</strong><small>{exam.rosterCandidateCount || 0} candidates · {rosterLabel(exam.rosterStatus)}</small></div>
            <Icon name="chevronRight" size={17} />
          </button>
          <button type="button" onClick={() => onNavigate('create-exam', { selectedExamId: exam.id })}>
            <span><Icon name="exam" size={19} /></span>
            <div><strong>Examination paper</strong><small>View the sealed paper and authoring record</small></div>
            <Icon name="chevronRight" size={17} />
          </button>
          <div className="admin-ops-context-panel__meta">
            <div><span>Roster health</span><RosterState status={exam.rosterStatus} /></div>
            <div><span>Revision</span><strong>Revision {exam.revisionNumber || 1}</strong></div>
            <div><span>Assessment</span><strong>{exam.assessmentName}</strong></div>
          </div>
        </aside>
      </div>

      {pendingAction === 'activate' ? (
        <ActivationReviewModal
          key={exam.id}
          exam={exam}
          exams={adminData.exams}
          gateway={gateway}
          onCancel={closeModal}
          onRefresh={() => refreshExams({ silent: false })}
          onActivated={() => setPendingAction(null)}
        />
      ) : pendingAction && (
        <OperationConfirmModal
          exam={exam}
          action={pendingAction}
          reason={reason}
          setReason={setReason}
          error={error}
          busy={busy}
          onCancel={closeModal}
          onConfirm={confirmAction}
        />
      )}
    </div>
  )
}

function OperationalExamRow({ exam, onOpen, selection }) {
  return (
    <article className={`admin-ops-timeline-row${needsAttention(exam) ? ' is-attention' : ''}${selection ? ' is-selectable' : ''}${selection?.selected ? ' is-selected' : ''}`}>
      {selection && <input className="admin-ops-bulk-checkbox" type="checkbox" aria-label={`Select ${exam.title}`} checked={selection.selected} disabled={selection.disabled} onChange={selection.toggle} />}
      <div className="admin-ops-timeline-time"><strong>{exam.scheduledStartAt ? formatClock(exam.scheduledStartAt) : '\u2014'}</strong><span>{formatDay(exam.scheduledStartAt)}</span></div>
      <span className={`admin-ops-timeline-marker admin-ops-timeline-marker--${exam.status}`}><ControlStateIcon status={exam.status} /></span>
      <button type="button" className="admin-ops-timeline-exam" onClick={onOpen}><strong>{exam.title}</strong><small>{exam.academicLevelName} · {exam.rosterCandidateCount || 0} candidates {"\u00b7"} {exam.durationMinutes || 0} min</small><ExamState status={exam.status} compact /></button>
      <button type="button" className="admin-ops-timeline-open" aria-label={`Open controls for ${exam.title}`} onClick={onOpen}><Icon name="chevronRight" size={18} /></button>
    </article>
  )
}

function DetailMetric({ label, value, helper }) {
  return <div className="admin-ops-detail-metric"><span>{label}</span><strong>{value}</strong><small>{helper}</small></div>
}

function ExamState({ status, compact = false }) {
  return <span className={`admin-ops-state admin-ops-state--${status}${compact ? ' is-compact' : ''}`}>{titleCase(status)}</span>
}

function RosterState({ status }) {
  return <span className={`admin-ops-roster-state admin-ops-roster-state--${status}`}>{rosterLabel(status)}</span>
}

function ControlStateIcon({ status }) {
  if (status === 'active' || status === 'sealed') return <RiPlayCircleLine size={24} />
  if (status === 'suspended') return <RiPauseCircleLine size={24} />
  if (status === 'closing' || status === 'closed') return <RiStopCircleLine size={24} />
  if (status === 'cancelling' || status === 'cancelled') return <RiCloseCircleLine size={24} />
  return <Icon name="operations" size={24} />
}

function controlsFor(exam) {
  if (exam.status === 'sealed') return [
    {
      action: 'activate',
      label: 'Activate examination',
      copy: exam.rosterStatus === 'ready' ? 'Open this sitting to candidates on the prepared roster.' : 'The candidate roster must be ready before activation.',
      Icon: RiPlayCircleLine,
      tone: 'primary',
      disabled: exam.rosterStatus !== 'ready',
    },
    { action: 'cancel', label: 'Cancel sitting', copy: 'Invalidate this sitting with a required audit reason.', Icon: RiCloseCircleLine, tone: 'danger' },
  ]
  if (exam.status === 'active') return [
    { action: 'suspend', label: 'Suspend examination', copy: 'Temporarily pause the live sitting while preserving candidate time.', Icon: RiPauseCircleLine, tone: 'warning' },
    { action: 'close', label: 'Close examination', copy: 'Permanently finish the sitting and finalize unfinished attempts.', Icon: RiStopCircleLine },
    { action: 'cancel', label: 'Cancel sitting', copy: 'Invalidate this sitting and terminate unfinished attempts.', Icon: RiCloseCircleLine, tone: 'danger' },
  ]
  if (exam.status === 'suspended') return [
    { action: 'resume', label: 'Resume examination', copy: 'Return this paused sitting to active execution.', Icon: RiPlayCircleLine, tone: 'primary' },
    { action: 'close', label: 'Close examination', copy: 'Permanently finish the sitting while it is suspended.', Icon: RiStopCircleLine },
    { action: 'cancel', label: 'Cancel sitting', copy: 'Invalidate the suspended sitting with an audit reason.', Icon: RiCloseCircleLine, tone: 'danger' },
  ]
  return []
}

function OperationConfirmModal({ exam, action, reason, setReason, error, busy, onCancel, onConfirm }) {
  const copy = operationCopy(action)
  const ActionIcon = copy.Icon
  return createPortal(
    <div className="admin-ops-confirm-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onCancel() }}>
      <section className={`admin-ops-confirm${copy.danger ? ' is-danger' : ''}`} role="alertdialog" aria-modal="true" aria-labelledby="admin-ops-confirm-title" aria-describedby="admin-ops-confirm-description">
        <div className="admin-ops-confirm__heading">
          <span><ActionIcon size={22} /></span>
          <div><h2 id="admin-ops-confirm-title">{copy.title}</h2><p id="admin-ops-confirm-description">{copy.description}</p></div>
        </div>
        <div className="admin-ops-confirm__exam"><span>Examination</span><strong>{exam.title}</strong><small>{exam.subjectName} · {exam.assessmentName}</small></div>
        {copy.reason && (
          <label className="admin-ops-confirm__reason">
            <span>Reason {requiresReason(action) ? '' : '(optional)'}</span>
            <textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} placeholder={copy.placeholder} />
          </label>
        )}
        <div className={`admin-ops-confirm__warning${copy.danger ? ' is-danger' : ''}`}><Icon name="info" size={17} /><span>{copy.warning}</span></div>
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="admin-ops-confirm__actions">
          <button type="button" className="admin-ops-confirm__cancel" disabled={busy} onClick={onCancel}>Go back</button>
          <button type="button" className={`admin-ops-confirm__submit${copy.danger ? ' is-danger' : ''}`} disabled={busy} onClick={onConfirm}>{busy ? 'Working…' : copy.confirm}</button>
        </div>
      </section>
    </div>,
    document.querySelector('.admin-ops-detail') || document.body,
  )
}

function operationCopy(action) {
  const copy = {
    suspend: {
      title: 'Suspend this examination?',
      description: 'The live sitting will pause while candidate execution state remains protected.',
      confirm: 'Suspend examination',
      Icon: RiPauseCircleLine,
      reason: true,
      placeholder: 'Explain why the live examination is being suspended.',
      warning: 'Use suspension for a temporary operational interruption that may be resumed.',
    },
    resume: {
      title: 'Resume this examination?',
      description: 'The suspended sitting will return to active execution.',
      confirm: 'Resume examination',
      Icon: RiPlayCircleLine,
      reason: true,
      placeholder: 'Optional note explaining why the sitting is being resumed.',
      warning: 'Candidates can continue this sitting with their saved progress and remaining time.',
    },
    close: {
      title: 'Close this examination?',
      description: 'Closing permanently ends this sitting and begins finalization of unfinished attempts.',
      confirm: 'Close examination',
      Icon: RiStopCircleLine,
      warning: 'Once closing begins, this sitting cannot return to ACTIVE. Suspend instead if the exam may need to continue.',
    },
    cancel: {
      title: 'Cancel this examination sitting?',
      description: 'Cancellation invalidates the sitting and terminates unfinished execution.',
      confirm: 'Cancel sitting',
      Icon: RiCloseCircleLine,
      danger: true,
      reason: true,
      placeholder: 'State the administrative reason for cancelling this sitting.',
      warning: 'Cancellation is an invalidation action, not a temporary pause. This transition cannot be reversed.',
    },
  }
  return copy[action]
}

function operationNotice(exam) {
  if (exam.rosterStatus === 'stale') return <Notice tone="warning">Enrollment changed in Weave. The roster is being reconciled automatically; activation remains unavailable until it returns to Ready.</Notice>
  if (exam.rosterStatus === 'failed') return <Notice tone="danger">{exam.rosterError || 'The candidate roster could not be prepared or reconciled. Resolve the roster issue before running this examination.'}</Notice>
  if (exam.status === 'closing') return <Notice tone="neutral">This examination is closing. Finalization is in progress and lifecycle controls are locked.</Notice>
  if (exam.status === 'cancelling') return <Notice tone="warning">This examination is being cancelled. Finalization is in progress and lifecycle controls are locked.</Notice>
  return null
}

function controlMessage(exam) {
  if (exam.status === 'sealed') return exam.rosterStatus === 'ready' ? 'This examination is ready for operational activation.' : 'This examination is waiting for a healthy candidate roster.'
  if (exam.status === 'active') return 'This examination is currently open to eligible candidates.'
  if (exam.status === 'suspended') return 'Candidate execution is temporarily paused.'
  if (exam.status === 'closing') return 'Saved candidate work is being finalized.'
  if (exam.status === 'cancelling') return 'This sitting is being cancelled.'
  if (exam.status === 'closed') return 'This examination has been permanently closed.'
  if (exam.status === 'cancelled') return 'This examination sitting has been cancelled.'
  return 'No operational controls are available.'
}

function controlDescription(exam) {
  if (exam.status === 'sealed') return exam.rosterStatus === 'ready'
    ? 'Activate when the examination centre is ready. This action is recorded in the examination audit history.'
    : `Roster status is ${rosterLabel(exam.rosterStatus)}. Open the roster to inspect preparation or reconciliation.`
  if (exam.status === 'active') return 'Use Suspend for a recoverable interruption. Close only when the sitting is genuinely finished.'
  if (exam.status === 'suspended') return 'Resume to continue the same sitting, or close/cancel it if execution should not continue.'
  if (exam.status === 'closing' || exam.status === 'cancelling') return 'This transition is irreversible. Controls remain unavailable until finalization completes.'
  return 'Historical execution state remains available for operational review.'
}

function terminalControlCopy(status) {
  if (status === 'closing') return 'Finalization is in progress. Reverse lifecycle actions are unavailable.'
  if (status === 'cancelling') return 'Cancellation finalization is in progress. Reverse lifecycle actions are unavailable.'
  if (status === 'closed') return 'This sitting is closed and read-only. Use Examinations if another paper revision is required.'
  if (status === 'cancelled') return 'This sitting is cancelled and read-only. A replacement revision is created from Examinations.'
  return 'No operational actions are currently available.'
}

function matchesTab(exam, tab) {
  if (tab === 'today') return true
  if (tab === 'ready') return exam.status === 'sealed' && exam.rosterStatus === 'ready'
  if (tab === 'live') return LIVE_STATUSES.has(exam.status)
  if (tab === 'upcoming') return exam.status === 'sealed' && Date.parse(exam.scheduledStartAt) > Date.now()
  if (tab === 'completed') return TERMINAL_STATUSES.has(exam.status)
  return true
}

function compareOperationalExams(left, right) {
  const priority = { active: 0, suspended: 1, closing: 2, cancelling: 3, sealed: 4, closed: 5, cancelled: 6 }
  const statusDelta = (priority[left.status] ?? 9) - (priority[right.status] ?? 9)
  if (statusDelta !== 0) return statusDelta
  const leftTime = left.scheduledStartAt ? new Date(left.scheduledStartAt).getTime() : Number.MAX_SAFE_INTEGER
  const rightTime = right.scheduledStartAt ? new Date(right.scheduledStartAt).getTime() : Number.MAX_SAFE_INTEGER
  return leftTime - rightTime
}

function needsAttention(exam) {
  return ['stale', 'failed'].includes(exam.rosterStatus) || ['suspended', 'cancelling'].includes(exam.status)
}

function isScheduledToday(exam, now) {
  if (!exam.scheduledStartAt) return false
  const date = new Date(exam.scheduledStartAt)
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
}


function scheduleSentence(exam) {
  if (!exam.scheduledStartAt) return 'No scheduled start time is attached to this examination.'
  return `Scheduled ${formatSchedule(exam.scheduledStartAt)} · ${exam.durationMinutes || 0} minutes`
}

function formatSchedule(value) {
  if (!value) return 'Not scheduled'
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}

function formatClock(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}

function formatDay(value) {
  if (!value) return 'Unscheduled'
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' }).format(new Date(value))
}

function rosterLabel(status) {
  const labels = {
    not_prepared: 'Not prepared',
    pending: 'Pending',
    building: 'Building',
    ready: 'Ready',
    stale: 'Stale',
    failed: 'Failed',
  }
  return labels[status] || titleCase(status)
}

function requiresReason(action) {
  return action === 'suspend' || action === 'cancel'
}

function titleCase(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}
