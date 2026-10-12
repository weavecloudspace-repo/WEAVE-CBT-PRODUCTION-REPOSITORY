import { useEffect, useState } from 'react'
import { Notice } from '../../shared/ui'
import { toStudentResolution } from '../../app/studentResolution'

export function StudentMakeupContinuation({ gateway, dispatch, onContinue }) {
  const [next, setNext] = useState(null)
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  useEffect(() => {
    let cancelled = false
    gateway.auth.getStudentStatus().then((session) => {
      if (!cancelled) { setNext(session); setError('') }
    }).catch((failure) => {
      if (!cancelled) setError(failure.userMessage || 'Could not check your next makeup. Please try again.')
    })
    return () => { cancelled = true }
  }, [gateway, version])
  const continueToNext = () => {
    onContinue?.()
    dispatch({ type: 'exam', patch: { stage: 'lobby', index: 0 } })
    dispatch({ type: 'studentResolution', resolution: toStudentResolution(next) })
  }
  return <div className="student-makeup-next">
    {error && <><Notice tone="danger">{error}</Notice><button className="premium-btn-secondary" onClick={() => setVersion((value) => value + 1)}>Check next makeup again</button></>}
    {!error && !next && <p role="status">Checking your approved makeup queue…</p>}
    {next?.availability === 'makeup' ? <><p>Next makeup: <strong>{next.subject_name || next.exam_title}</strong></p><button className="premium-btn-primary" onClick={continueToNext}>Continue to next makeup</button></> : next && <p>{next.status_message}</p>}
  </div>
}
