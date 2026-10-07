import { useEffect, useMemo, useRef, useState } from 'react'
import { DashboardSchoolIdentity, Notice, StatusBadge } from '../../shared/ui'
import { FormattedText } from '../../shared/ui/FormattedText'
import './student.css'
import { StudentLogoutConfirmation } from './StudentLogoutConfirmation'
import { ProductLoadingScreen } from '../../app/ProductLoadingScreen'
import { getLocalBrandLogoSrc } from '../../api/branding'
import { RiCheckboxCircleFill, RiFlagFill, RiLogoutBoxRLine, RiDatabase2Line, RiArrowLeftLine, RiArrowRightLine } from '@remixicon/react'

const HEARTBEAT_RETRY_MS = 10_000
const TIMEOUT_RETRY_MS = 3_000

export function StudentWorkspace(props) {
  return (
    <StudentLogoutConfirmation onLogout={props.returnToSignIn}>
      {(requestLogout) => <StudentWorkspaceContent {...props} requestLogout={requestLogout} />}
    </StudentLogoutConfirmation>
  )
}

function StudentWorkspaceContent({ exam, resolution, gateway, dispatch, returnToSignIn, requestLogout, branding, schoolName, serverName = 'Local CBT server', onExamSuspended }) {
  const [attempt, setAttempt] = useState(null)
  const [attemptError, setAttemptError] = useState('')
  const [attemptLoadVersion, setAttemptLoadVersion] = useState(0)
  const [savingByQuestion, setSavingByQuestion] = useState({})
  const [submitted, setSubmitted] = useState(null)
  const [submissionRequested, setSubmissionRequested] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [timeoutSubmitting, setTimeoutSubmitting] = useState(false)
  const submissionDialogRef = useRef(null)
  const submissionPending = useRef(false)
  const timeoutPending = useRef(false)
  const [starting, setStarting] = useState(false)
  const [suspension, setSuspension] = useState(null)
  const suspensionHandled = useRef(false)
  const startPending = useRef(false)
  const pendingSaves = useRef(new Set())
  const [clock, setClock] = useState(() => Date.now())
  const isSuspended = exam.stage === 'active' && Boolean(suspension || attempt?.exam_suspended || resolution?.state === 'suspended')
  const interrupted = exam.stage === 'active' && attempt?.status === 'interrupted'
  const remaining = Math.max(0, (attempt?.remaining_seconds || 0) - (attempt?.exam_suspended || attempt?.status !== 'in_progress' ? 0 : Math.floor(Math.max(0, clock - (attempt?.clock_received_at || clock)) / 1000)))

  useEffect(() => {
    if (exam.stage !== 'active' || !attempt?.id || submitted || isSuspended || interrupted) return undefined
    const tick = () => setClock(Date.now())
    const timer = window.setInterval(tick, 250)
    document.addEventListener('visibilitychange', tick)
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', tick) }
  }, [exam.stage, attempt?.id, submitted, isSuspended, interrupted])

  const questions = useMemo(() => attempt?.questions || [], [attempt])
  const current = questions[exam.index] || questions[0]

  useEffect(() => {
    if (submissionRequested && !isSuspended) submissionDialogRef.current?.showModal()
  }, [submissionRequested, isSuspended])

  const confirmSubmission = async () => {
    if (submissionPending.current || pendingSaves.current.size > 0) return
    submissionPending.current = true
    setSubmitting(true)
    setSubmissionRequested(false)
    try {
      await submitAttempt({ gateway, setSubmitted, dispatch, setAttemptError })
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  const candidateName = resolution?.candidate?.name?.trim() || 'Student'
  const candidateInitial = Array.from(candidateName)[0].toLocaleUpperCase()

  useEffect(() => {
    if (!isSuspended || suspensionHandled.current) return
    suspensionHandled.current = true
    onExamSuspended?.(suspension?.message || (resolution?.state === 'suspended' ? resolution.statusMessage : undefined))
  }, [isSuspended, onExamSuspended, resolution, suspension])

  useEffect(() => {
    if (exam.stage === 'active') return
    suspensionHandled.current = false
    timeoutPending.current = false
    setTimeoutSubmitting(false)
    setSuspension(null)
    setAttempt(null)
  }, [exam.stage])

  useEffect(() => {
    if (exam.stage !== 'active') return undefined
    let cancelled = false
    gateway.attempts
      .getCurrentAttempt()
      .then((currentAttempt) => {
        if (!cancelled) setAttempt({ ...currentAttempt, clock_received_at: Date.now() })
      })
      .catch((error) => {
        if (cancelled) return
        if (error?.status === 401) {
          returnToSignIn()
          return
        }
        setAttemptError(error?.userMessage || 'Weave could not reopen this active attempt.')
      })
    return () => { cancelled = true }
  }, [exam.stage, gateway, returnToSignIn, attemptLoadVersion])

  useEffect(() => {
    if (exam.stage !== 'active' || !attempt?.id || submitted || isSuspended) return undefined
    let stopped = false
    let timerId = null

    const schedule = (milliseconds) => {
      if (!stopped) timerId = window.setTimeout(sendHeartbeat, milliseconds)
    }

    const sendHeartbeat = async () => {
      try {
        const heartbeat = await gateway.attempts.heartbeatCurrentAttempt()
        if (stopped) return
        setAttempt((currentAttempt) => currentAttempt ? {
          ...currentAttempt,
          remaining_seconds: heartbeat.remaining_seconds,
          clock_received_at: Date.now(),
          status: heartbeat.status,
          exam_suspended: heartbeat.exam_suspended,
        } : currentAttempt)
        const nextSeconds = Number(heartbeat.next_heartbeat_after_seconds) || 20
        schedule(Math.max(5, nextSeconds) * 1000)
      } catch (error) {
        if (error?.status === 401) {
          if (!stopped) returnToSignIn()
          return
        }
        try {
          const status = await gateway.auth.getStudentStatus()
          if (!stopped && status.availability === 'suspended') { setSuspension({ message: status.status_message }); return }
        } catch (statusError) {
          if (statusError?.status === 401) {
            if (!stopped) returnToSignIn()
            return
          }
        }
        // Connectivity loss alone never changes academic state.
        schedule(HEARTBEAT_RETRY_MS)
      }
    }

    sendHeartbeat()
    const handleVisibility = () => {
      if (!document.hidden && !stopped) {
        if (timerId) window.clearTimeout(timerId)
        sendHeartbeat()
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      stopped = true
      if (timerId) window.clearTimeout(timerId)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [attempt?.id, exam.stage, gateway, submitted, isSuspended, returnToSignIn])

  useEffect(() => {
    if (
      exam.stage !== 'active'
      || !attempt?.id
      || attempt.status !== 'in_progress'
      || remaining > 0
      || submitted
      || isSuspended
      || timeoutPending.current
    ) return undefined

    let cancelled = false
    let retryId = null
    timeoutPending.current = true
    setTimeoutSubmitting(true)
    setSubmissionRequested(false)
    setAttemptError('')

    const finalizeTimeout = async () => {
      if (cancelled) return
      if (pendingSaves.current.size > 0) {
        retryId = window.setTimeout(finalizeTimeout, 250)
        return
      }
      try {
        const result = await gateway.attempts.submitCurrentAttempt()
        if (cancelled) return
        setSubmitted(result)
        dispatch({ type: 'exam', patch: { stage: 'submitted' } })
      } catch (error) {
        if (cancelled) return
        if (error?.status === 401) {
          returnToSignIn()
          return
        }
        setAttemptError(error?.userMessage || 'Time is up. Weave is retrying final submission automatically.')
        retryId = window.setTimeout(finalizeTimeout, TIMEOUT_RETRY_MS)
      }
    }

    void finalizeTimeout()
    return () => {
      cancelled = true
      if (retryId) window.clearTimeout(retryId)
    }
  }, [attempt?.id, attempt?.status, dispatch, exam.stage, gateway, isSuspended, remaining, returnToSignIn, submitted])

  if (isSuspended) return <main className="premium-exam-shell"><section className="premium-lobby-card"><h1>Exam currently suspended</h1><p>Returning you to the waiting room. Your session and saved answers are protected.</p></section></main>

  if (exam.stage === 'submitted' || submitted) {
    return <main className="premium-exam-shell premium-exam-shell--submitted"><StudentExamSubmittedCard result={submitted} onLogout={requestLogout} /></main>
  }

  if (timeoutSubmitting) {
    return <main className="premium-exam-shell"><section className="premium-lobby-card" role="status"><StatusBadge tone="warning">Time expired</StatusBadge><h1>Time is up</h1><p>Weave is submitting your saved answers automatically. Keep this page open while the submission is confirmed.</p>{attemptError && <Notice tone="warning">{attemptError}</Notice>}</section></main>
  }

  if (interrupted) {
    return <main className="premium-exam-shell"><section className="premium-lobby-card" role="status"><StatusBadge tone="warning">Attempt paused</StatusBadge><h1>Your examination has been paused</h1><p>Your attempt has been temporarily paused. Your saved answers are safe and your timer is paused.</p><Notice>Please remain at your computer. The examination will reopen automatically when your attempt is resumed.</Notice></section></main>
  }

  if (exam.stage === 'active') {
    if (!attempt || !current) {
      return (
        <ProductLoadingScreen
          title="Starting Weave"
          copy="Checking the local CBT server and installation state."
          error={attemptError}
          onRetry={() => { setAttemptError(''); setAttemptLoadVersion((value) => value + 1) }}
        />
      )
    }

    const answeredCount = questions.filter((question) => question.selected_option_ids.length > 0).length
    const isSaving = Object.values(savingByQuestion).includes('Saving...')
    const unansweredCount = questions.length - answeredCount

    return (
      <main className="premium-exam-shell premium-exam-shell--session">
        <div className="premium-exam-frame">
          <aside className="premium-exam-rail premium-exam-sidebar" aria-label="Exam progress">
            <div className="premium-exam-rail-brand"><DashboardSchoolIdentity schoolName={branding?.school_name || schoolName || 'School'} logoSrc={getLocalBrandLogoSrc(branding)} /></div>
            <div className="premium-exam-rail-timer"><ExamCountdownTimer remaining={remaining} totalSeconds={attempt.time_limit_seconds} /></div>
            <div className="premium-exam-progress"><div><strong>{answeredCount}<span> / {questions.length}</span></strong><span>Answered</span></div><progress aria-label="Questions answered" value={answeredCount} max={questions.length} /></div>
            <div className="premium-question-nav">
              <div className="premium-question-nav__head"><h3>Questions</h3><span className="premium-question-nav__meta">{answeredCount} of {questions.length} answered</span></div>
              <div className="premium-nav-grid">
                {questions.map((question, index) => <button key={question.id} aria-label={`Question ${index + 1}${question.is_flagged ? ', marked for review' : ''}`} aria-current={index === exam.index ? 'step' : undefined} className={`nav-btn ${question.is_flagged ? 'flagged' : ''} ${index === exam.index ? 'current' : ''} ${question.selected_option_ids.length > 0 && index !== exam.index ? 'answered' : ''}`} onClick={() => dispatch({ type: 'exam', patch: { index } })}>{index + 1}{question.is_flagged && <RiFlagFill className="premium-review-flag" size={12} aria-hidden="true" />}</button>)}
              </div>
            </div>
            <div className="premium-exam-rail-submit">
              <button type="button" className="premium-exam-rail-submit-btn" disabled={isSaving || submitting} onClick={() => setSubmissionRequested(true)}>Submit exam</button>
              {unansweredCount > 0 && <p className="premium-exam-rail-submit-note">{unansweredCount} question{unansweredCount === 1 ? '' : 's'} not answered</p>}
            </div>
          </aside>
          <div className="premium-exam-stage">
            <StudentExamHeader title={attempt.exam_title} branding={branding} schoolName={schoolName} serverName={serverName} candidateName={candidateName} candidateInitial={candidateInitial} onLogout={() => requestLogout({ timerContinues: true })} layout="session" />
            <div className="premium-exam-content">
              <section className="premium-question-paper" aria-labelledby="candidate-question-heading">
                <div className="premium-question-header">
                  <div className="premium-question-heading"><span className="premium-question-eyebrow">{current.question_type === 'multiple_choice' ? 'Multiple choice' : 'Single choice'}</span><h2 id="candidate-question-heading">Question {exam.index + 1}<span> of {questions.length}</span></h2></div>
                  <div className="premium-question-toolbar">
                    {current.selected_option_ids.length > 0 && <button type="button" className="premium-clear-choice" disabled={savingByQuestion[current.id] === 'Saving...'} onClick={() => saveAnswer({ question: current, clearSelection: true, gateway, setAttempt, setSavingByQuestion, setAttemptError, pendingSaves })}>Clear choice</button>}
                    <label className="premium-mark-review"><input type="checkbox" checked={Boolean(current.is_flagged)} disabled={savingByQuestion[current.id] === 'Saving...'} onChange={() => saveAnswer({ question: current, flagged: !current.is_flagged, gateway, setAttempt, setSavingByQuestion, setAttemptError, pendingSaves })} /> Mark for review</label>
                  </div>
                </div>
                {current.instruction && <p className="premium-question-instruction"><FormattedText text={current.instruction} /></p>}
                <div className="premium-question-prompt"><FormattedText text={current.prompt} /></div>
                {current.image_asset_id && <div className="premium-question-media"><AttemptMedia gateway={gateway} questionId={current.id} alt="Question illustration" /></div>}
                <div className="premium-options-list">
                  {current.options.map((option, index) => {
                    const selected = current.selected_option_ids.includes(option.id)
                    return (
                      <label key={option.id} className={`premium-option ${selected ? 'selected' : ''}`}>
                        <input type={current.question_type === 'multiple_choice' ? 'checkbox' : 'radio'} className="premium-option-input" name={`question-${current.id}`} aria-label={`Option ${optionLetter(index)}: ${option.text || 'Image answer'}`} checked={selected} disabled={savingByQuestion[current.id] === 'Saving...'} onChange={() => saveAnswer({ question: current, optionId: option.id, gateway, setAttempt, setSavingByQuestion, setAttemptError, pendingSaves })} />
                        <div className="premium-option-letter">{optionLetter(index)}</div>
                        <div className="premium-option-content">{option.text && <div className="premium-option-text">{option.text}</div>}{option.image_asset_id && <div className="premium-option-media"><AttemptMedia gateway={gateway} questionId={current.id} optionId={option.id} alt={`Option ${optionLetter(index)}`} /></div>}</div>
                        <span className={`premium-option-indicator${current.question_type === 'multiple_choice' ? ' is-multiple' : ''}`} aria-hidden="true">{selected && <RiCheckboxCircleFill size={22} />}</span>
                      </label>
                    )
                  })}
                </div>
                <span className="premium-answer-status" role="status">{savingByQuestion[current.id] === 'Saving...' ? 'Saving answer...' : savingByQuestion[current.id] === 'Not saved' ? 'Answer not saved' : current.selected_option_ids.length > 0 ? 'Answer saved' : 'No answer selected'}</span>
                {attemptError && <div className="premium-exam-content__notice"><Notice tone="danger">{attemptError}</Notice></div>}
                <nav className="premium-exam-navigation" aria-label="Question navigation">
                  <button className="premium-btn-secondary" onClick={() => dispatch({ type: 'exam', patch: { index: Math.max(0, exam.index - 1) } })} disabled={exam.index === 0}><RiArrowLeftLine size={18} aria-hidden="true" /><span>Previous</span></button>
                  {exam.index < questions.length - 1 ? <button className="premium-btn-primary" onClick={() => dispatch({ type: 'exam', patch: { index: exam.index + 1 } })}><span>Save and next</span><RiArrowRightLine size={18} aria-hidden="true" /></button> : <button className="premium-btn-primary" disabled={isSaving || submitting} onClick={() => setSubmissionRequested(true)}>Submit exam</button>}
                </nav>
              </section>
            </div>
          </div>
        </div>
        {submissionRequested && (
          <dialog ref={submissionDialogRef} className="student-logout-dialog" aria-labelledby="student-submit-title" aria-describedby="student-submit-description" onCancel={() => setSubmissionRequested(false)} onClose={() => setSubmissionRequested(false)}>
            <h2 id="student-submit-title">Confirm exam submission</h2>
            <p id="student-submit-description">{unansweredCount > 0 ? `You have not answered ${unansweredCount} question${unansweredCount === 1 ? '' : 's'}. Are you sure you want to submit anyway?` : 'You have answered all questions. Are you sure you want to submit?'}</p>
            <div className="student-logout-dialog__actions"><button className="premium-btn-secondary" type="button" autoFocus onClick={() => setSubmissionRequested(false)}>Cancel</button><button className="premium-btn-primary" type="button" disabled={isSaving || submitting} onClick={confirmSubmission}>Confirm submission</button></div>
          </dialog>
        )}
      </main>
    )
  }

  const state = resolution?.state || 'no_exam'
  const noExam = state === 'no_exam'
  const waiting = state === 'waiting_for_activation'
  const suspended = state === 'suspended'
  const unavailable = noExam || waiting || suspended
  const canResume = resolution?.hasUnfinishedAttempt === true
  const ready = state === 'ready' || state === 'makeup'
  const title = noExam ? 'No exam available yet' : resolution?.exam?.title || 'Current examination'
  const statusLabel = noExam ? 'Waiting room' : waiting ? 'Waiting for activation' : suspended ? 'Exam suspended' : canResume ? 'Ready to resume' : state === 'makeup' ? 'Makeup exam ready' : 'Exam ready'

  return (
    <main className="premium-exam-shell" style={{ justifyContent: 'center', alignItems: 'center' }}>
      <section className="premium-lobby-card">
        <StatusBadge tone={unavailable ? 'warning' : 'success'}>{statusLabel}</StatusBadge>
        <h1>{title}</h1>
        <p>{resolution?.statusMessage || (noExam ? 'Stay on this page. Weave will update automatically when an exam becomes available.' : 'Check the details below before you begin.')}</p>
        {unavailable && <Notice>Weave is checking the local CBT server automatically. You do not need to sign in again.</Notice>}
        {ready && <Notice>Your examination has been resolved from the local CBT server and is ready to open.</Notice>}
        {attemptError && <Notice tone="danger">{attemptError}</Notice>}
        <button className="premium-btn-primary" style={{ width: '100%', marginTop: '24px' }} disabled={unavailable || starting} onClick={() => startAttempt({ gateway, setAttempt, dispatch, setAttemptError, setStarting, onExamSuspended, startPending, expectedExamId: resolution?.exam?.id })}>{starting ? 'Checking exam status...' : noExam ? 'Waiting for an exam...' : waiting ? 'Waiting for activation...' : suspended ? 'Waiting for exam to resume...' : canResume ? 'Resume attempt' : 'Start Exam'}</button>
        <button className="premium-btn-secondary" type="button" onClick={() => requestLogout()} style={{ width: '100%', marginTop: '12px' }}>Logout</button>
      </section>
    </main>
  )
}

const SUBMISSION_SCORE_RADIUS = 58
const SUBMISSION_SCORE_CIRCUMFERENCE = 2 * Math.PI * SUBMISSION_SCORE_RADIUS

function StudentExamSubmittedCard({ result, onLogout }) {
  const scoreValue = result ? `${result.raw_score} / ${result.raw_max_score}` : null
  const percentage = result ? Math.min(100, Math.max(0, Number.parseFloat(result.percentage) || 0)) : null
  const progress = percentage === null ? 0 : percentage / 100
  const offset = SUBMISSION_SCORE_CIRCUMFERENCE * (1 - progress)
  return (
    <section className="premium-submission-card" aria-labelledby="submission-title">
      <div className="premium-submission-card__glow" aria-hidden="true" />
      <div className="premium-submission-card__hero"><span className="premium-submission-card__icon" aria-hidden="true"><RiCheckboxCircleFill size={40} /></span><h1 id="submission-title">Exam submitted</h1><p className="premium-submission-card__lead">Your answers are saved. You may sign out when ready.</p></div>
      {result && <div className="premium-submission-score" aria-label={`Score ${scoreValue}, ${result.percentage} percent`}><div className="premium-submission-score__ring"><svg viewBox="0 0 140 140" aria-hidden="true"><circle className="premium-submission-score__track" cx="70" cy="70" r={SUBMISSION_SCORE_RADIUS} /><circle className="premium-submission-score__progress" cx="70" cy="70" r={SUBMISSION_SCORE_RADIUS} style={{ strokeDasharray: SUBMISSION_SCORE_CIRCUMFERENCE, strokeDashoffset: offset }} /></svg><div className="premium-submission-score__face"><strong>{result.percentage}%</strong><span>{scoreValue}</span></div></div></div>}
      <button className="premium-btn-primary premium-submission-card__logout" type="button" onClick={() => onLogout()}>Logout</button>
    </section>
  )
}

function StudentExamHeader({ title, branding, schoolName, serverName, candidateName, candidateInitial, onLogout, layout = 'standalone' }) {
  const session = layout === 'session'
  return (
    <header className={`premium-exam-header${session ? ' premium-exam-header--session' : ''}`}>
      <div className="premium-exam-header__inner">
        <div className="premium-exam-header-left">{!session && <DashboardSchoolIdentity schoolName={branding?.school_name || schoolName || 'School'} logoSrc={getLocalBrandLogoSrc(branding)} />}{session && <div className="premium-exam-session-title premium-exam-session-title--solo"><p className="premium-exam-session-eyebrow">Examination</p><h1>{title}</h1></div>}</div>
        {!session && <div className="premium-exam-server" title={serverName}><span><RiDatabase2Line size={18} aria-hidden="true" /></span><div><small>CBT server</small><strong>{serverName}</strong></div></div>}
        <div className="premium-exam-header-right">
          {session ? <div className="premium-exam-header-account"><span className="student-avatar" aria-hidden="true">{candidateInitial}</span><strong className="premium-student-name" title={candidateName}>{candidateName}</strong><button className="premium-student-logout" type="button" onClick={onLogout} aria-label="Logout"><RiLogoutBoxRLine size={18} aria-hidden="true" /></button></div> : <><div className="premium-student-identity"><span className="student-avatar" aria-hidden="true">{candidateInitial}</span><strong className="premium-student-name" title={candidateName}>{candidateName}</strong></div><button className="premium-student-logout" type="button" onClick={onLogout}><RiLogoutBoxRLine size={17} aria-hidden="true" /><span>Logout</span></button></>}
        </div>
        {!session && title && <div className="premium-exam-title"><h1>{title}</h1></div>}
      </div>
    </header>
  )
}

function ExamCountdownTimer({ remaining, totalSeconds }) {
  const radius = 50
  const circumference = 2 * Math.PI * radius
  const safeTotal = Math.max(Number(totalSeconds) || 0, Number(remaining) || 0, 1)
  const progress = Math.min(1, Math.max(0, (Number(remaining) || 0) / safeTotal))
  const offset = circumference * (1 - progress)
  const urgent = remaining <= 300
  const critical = remaining <= 120
  return <div className={`premium-exam-timer${urgent ? ' is-urgent' : ''}${critical ? ' is-critical' : ''}`} role="timer" aria-live="off" aria-label={`Time remaining ${formatRemaining(remaining)}`}><div className="premium-exam-timer__ring"><svg viewBox="0 0 120 120" aria-hidden="true"><circle className="premium-exam-timer__track" cx="60" cy="60" r={radius} /><circle className="premium-exam-timer__progress" cx="60" cy="60" r={radius} style={{ strokeDasharray: circumference, strokeDashoffset: offset }} /></svg><div className="premium-exam-timer__face"><span className="premium-exam-timer__label">Time left</span><strong className="premium-exam-timer__value" key={Math.floor(remaining / 60)}>{formatRemaining(remaining)}</strong></div></div></div>
}

function AttemptMedia({ gateway, questionId, optionId, alt }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let cancelled = false
    let objectUrl = ''
    const request = optionId ? gateway.attempts.getCurrentOptionImage(questionId, optionId) : gateway.attempts.getCurrentQuestionImage(questionId)
    request.then((blob) => { if (cancelled) return; objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) }).catch(() => null)
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [gateway, optionId, questionId])
  return url ? <img src={url} alt={alt} /> : <span className="premium-media-loading">Loading image…</span>
}

async function startAttempt({ gateway, setAttempt, dispatch, setAttemptError, setStarting, onExamSuspended, startPending, expectedExamId }) {
  if (startPending.current) return
  startPending.current = true
  setStarting(true)
  setAttemptError('')
  try {
    const status = await gateway.auth.getStudentStatus()
    if (status.availability === 'suspended') { onExamSuspended?.(status.status_message); return }
    if (!['ready', 'makeup'].includes(status.availability) || status.exam_id !== expectedExamId) { setAttemptError(status.status_message || 'This examination is not currently available. Please wait for the examination to become available.'); return }
    const attempt = await gateway.attempts.startCurrentAttempt()
    if (attempt.exam_suspended) { onExamSuspended?.(); return }
    setAttempt({ ...attempt, clock_received_at: Date.now() })
    dispatch({ type: 'exam', patch: { stage: 'active', index: 0 } })
  } catch (error) {
    try { const status = await gateway.auth.getStudentStatus(); if (status.availability === 'suspended') { onExamSuspended?.(status.status_message); return } } catch { /* Preserve start failure. */ }
    setAttemptError(error.userMessage || 'Weave could not start this attempt. Please try again.')
  } finally {
    startPending.current = false
    setStarting(false)
  }
}

async function saveAnswer({ question, optionId, clearSelection = false, flagged = question.is_flagged, gateway, setAttempt, setSavingByQuestion, setAttemptError, pendingSaves }) {
  if (pendingSaves.current.has(question.id)) return
  pendingSaves.current.add(question.id)
  const selectedOptionIds = clearSelection ? [] : optionId === undefined ? question.selected_option_ids : question.question_type === 'multiple_choice' ? question.selected_option_ids.includes(optionId) ? question.selected_option_ids.filter((id) => id !== optionId) : [...question.selected_option_ids, optionId] : [optionId]
  const mutationSequence = question.mutation_sequence + 1
  setAttemptError('')
  setSavingByQuestion((current) => ({ ...current, [question.id]: 'Saving...' }))
  setAttempt((currentAttempt) => ({ ...currentAttempt, questions: currentAttempt.questions.map((item) => item.id === question.id ? { ...item, selected_option_ids: selectedOptionIds, is_flagged: flagged, mutation_sequence: mutationSequence } : item) }))
  try {
    const saved = await gateway.attempts.saveCurrentAnswer(question.id, { mutation_sequence: mutationSequence, selected_option_ids: selectedOptionIds, is_flagged: flagged })
    setAttempt((currentAttempt) => ({ ...currentAttempt, remaining_seconds: saved.remaining_seconds, clock_received_at: Date.now(), questions: currentAttempt.questions.map((item) => item.id === question.id ? { ...item, selected_option_ids: saved.selected_option_ids, mutation_sequence: saved.mutation_sequence, is_flagged: saved.is_flagged } : item) }))
    setSavingByQuestion((current) => ({ ...current, [question.id]: 'Saved' }))
  } catch (error) {
    setAttempt((currentAttempt) => ({ ...currentAttempt, questions: currentAttempt.questions.map((item) => item.id === question.id ? { ...item, selected_option_ids: question.selected_option_ids, is_flagged: question.is_flagged } : item) }))
    setSavingByQuestion((current) => ({ ...current, [question.id]: 'Not saved' }))
    setAttemptError(error.userMessage || 'Your change could not be saved. Please try again.')
  } finally {
    pendingSaves.current.delete(question.id)
  }
}

async function submitAttempt({ gateway, setSubmitted, dispatch, setAttemptError }) {
  setAttemptError('')
  try {
    const result = await gateway.attempts.submitCurrentAttempt()
    setSubmitted(result)
    dispatch({ type: 'exam', patch: { stage: 'submitted' } })
  } catch (error) {
    setAttemptError(error.userMessage || 'Weave could not submit the attempt.')
  }
}

function optionLetter(index) { return String.fromCharCode(65 + (index % 26)) }
function formatRemaining(seconds) {
  const safe = Math.max(0, Number(seconds) || 0)
  const minutes = Math.floor(safe / 60)
  const remainder = safe % 60
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}
