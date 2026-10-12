import { useEffect, useState } from 'react'
import { RiCheckboxCircleFill } from '@remixicon/react'
import { Notice } from '../../shared/ui'
import './student.css'
import { StudentLogoutConfirmation } from './StudentLogoutConfirmation'
import { StudentMakeupContinuation } from './StudentMakeupContinuation'

const SCORE_RADIUS = 58
const SCORE_CIRCUMFERENCE = 2 * Math.PI * SCORE_RADIUS

export function StudentCompletedExamPage(props) {
  return (
    <StudentLogoutConfirmation onLogout={props.returnToSignIn}>
      {(requestLogout) => <StudentCompletedExamContent {...props} returnToSignIn={requestLogout} />}
    </StudentLogoutConfirmation>
  )
}

function StudentCompletedExamContent({ gateway, returnToSignIn, dispatch, isMakeup = false }) {
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    gateway.attempts
      .getCurrentAttemptResult()
      .then((payload) => {
        if (!cancelled) { setError(''); setResult(payload) }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(requestError.userMessage || 'Weave could not load your completed examination result.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [gateway, refreshToken])

  if (!result) {
    return (
      <main className="premium-exam-shell premium-exam-shell--submitted">
        <section className="premium-submission-card" aria-labelledby="completed-result-title">
          <div className="premium-submission-card__hero">
            <h1 id="completed-result-title">Your exam is complete</h1>
            <p className="premium-submission-card__lead">
              {error ? 'Your attempt has ended, but the score could not be loaded.' : 'Loading your score…'}
            </p>
          </div>
          {error && <Notice tone="danger">{error}</Notice>}
          {error && (
            <button
              className="premium-btn-primary premium-submission-card__logout"
              type="button"
              onClick={() => { setError(''); setRefreshToken((value) => value + 1) }}
            >
              Try again
            </button>
          )}
          <button className="premium-btn-secondary" type="button" onClick={returnToSignIn}>Logout</button>
        </section>
      </main>
    )
  }

  const scoreValue = `${result.raw_score} / ${result.raw_max_score}`
  const percentage = Math.min(100, Math.max(0, Number.parseFloat(result.percentage) || 0))
  const offset = SCORE_CIRCUMFERENCE * (1 - percentage / 100)

  return (
    <main className="premium-exam-shell premium-exam-shell--submitted">
      <section className="premium-submission-card" aria-labelledby="completed-result-title">
        <div className="premium-submission-card__glow" aria-hidden="true" />
        <div className="premium-submission-card__hero">
          <span className="premium-submission-card__icon" aria-hidden="true">
            <RiCheckboxCircleFill size={40} />
          </span>
          <h1 id="completed-result-title">{result.voided_at ? 'Result voided' : 'Exam submitted'}</h1>
          <p className="premium-submission-card__subject">{result.subject_name}</p>
          <p className="premium-submission-card__lead">{result.voided_at ? 'Your result has been voided by an administrator. Contact the school for guidance.' : 'You have already completed this examination. Here is your recorded score.'}</p>
        </div>
        {!result.voided_at && <div className="premium-submission-score" aria-label={`Score ${scoreValue}, ${result.percentage} percent`}>
          <div className="premium-submission-score__ring">
            <svg viewBox="0 0 140 140" aria-hidden="true">
              <circle className="premium-submission-score__track" cx="70" cy="70" r={SCORE_RADIUS} />
              <circle
                className="premium-submission-score__progress"
                cx="70"
                cy="70"
                r={SCORE_RADIUS}
                style={{ strokeDasharray: SCORE_CIRCUMFERENCE, strokeDashoffset: offset }}
              />
            </svg>
            <div className="premium-submission-score__face">
              <strong>{result.percentage}%</strong>
              <span>{scoreValue}</span>
            </div>
          </div>
        </div>}
        {isMakeup && <StudentMakeupContinuation gateway={gateway} dispatch={dispatch} />}
        <button className="premium-btn-primary premium-submission-card__logout" type="button" onClick={returnToSignIn}>Logout</button>
      </section>
    </main>
  )
}
