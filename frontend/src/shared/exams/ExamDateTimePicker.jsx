import { useEffect, useId, useRef, useState } from 'react'
import { RiCalendarLine, RiArrowLeftSLine, RiArrowRightSLine, RiCloseLine, RiTimeLine } from '@remixicon/react'
import { SelectControl } from '../ui'
import './exam-date-time-picker.css'

const pad = (value) => String(value).padStart(2, '0')
const dateKey = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const localMinute = (date) => `${dateKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
const dateLabel = (date) => date.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })
const timeOptions = (count) => Array.from({ length: count }, (_, value) => ({ value: pad(value), label: pad(value) }))
const HOURS = timeOptions(24)
const MINUTES = timeOptions(60)

function nextLocalMinute() {
  const date = new Date(Date.now() + 60_000)
  return localMinute(date)
}

function hasElapsed(value, now) {
  if (!value) return false
  const timestamp = new Date(value).getTime()
  return Number.isFinite(timestamp) && timestamp <= now
}

export function ExamDateTimePicker({ label, value, onChange, min = '', minExclusive = false, disabled = false }) {
  const dialogRef = useRef(null)
  const headingId = useId()
  const helpId = useId()
  const elapsedHelpId = useId()
  const [draft, setDraft] = useState('')
  const [month, setMonth] = useState(() => new Date())
  const [opened, setOpened] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const entryDeadline = label === 'Latest normal start'
  const displayLabel = entryDeadline ? 'Normal entry deadline' : label
  const currentMinimum = nextLocalMinute()
  const earliestFromSchedule = min && minExclusive
    ? localMinute(new Date(new Date(min).getTime() + 60_000))
    : min
  const effectiveMin = earliestFromSchedule && earliestFromSchedule > currentMinimum ? earliestFromSchedule : currentMinimum
  const selectedDate = draft.slice(0, 10)
  const hours = draft.slice(11, 13) || '09'
  const minutes = draft.slice(14, 16) || '00'
  const tooEarly = Boolean(effectiveMin && draft && draft < effectiveMin)
  const valueElapsed = hasElapsed(value, now)
  const invalidEntryWindow = Boolean(minExclusive && min && value && new Date(value).getTime() <= new Date(min).getTime())
  const firstDay = new Date(month.getFullYear(), month.getMonth(), 1).getDay()
  const dayCount = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const today = dateKey(new Date())

  useEffect(() => {
    if (!value) return undefined
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [value])

  const open = () => {
    const initial = valueElapsed ? effectiveMin : value || effectiveMin || `${today}T09:00`
    setDraft(initial)
    setMonth(new Date(`${initial.slice(0, 10)}T12:00`))
    setOpened(true)
    dialogRef.current.showModal()
  }
  const close = () => dialogRef.current.close()
  const changeTime = (hour, minute) => setDraft(`${selectedDate}T${hour}:${minute}`)
  const moveMonth = (offset) => setMonth(new Date(month.getFullYear(), month.getMonth() + offset, 1))

  return (
    <div className="teacher-exam-field exam-datetime">
      <span>{displayLabel} <small>(optional)</small></span>
      <button
        type="button"
        className={`exam-datetime__trigger${value ? ' has-value' : ''}${valueElapsed ? ' is-overdue' : ''}`}
        aria-label={displayLabel}
        aria-haspopup="dialog"
        aria-describedby={valueElapsed ? elapsedHelpId : undefined}
        disabled={disabled}
        onClick={open}
      >
        <RiCalendarLine size={18} aria-hidden="true" />
        <span>{value ? new Date(value).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Choose date & time'}</span>
      </button>
      {entryDeadline && !valueElapsed && <p className="exam-datetime__hint">Students can start normally until this time. After it passes, an administrator must grant late-start access.</p>}
      {valueElapsed && (
        <p id={elapsedHelpId} className="exam-datetime__elapsed" role="alert">
          This time has elapsed. Choose a new future time before saving or moving this examination forward.
        </p>
      )}
      {invalidEntryWindow && <p className="exam-datetime__elapsed" role="alert">Normal entry deadline must be after the scheduled start. Equal times leave no time for candidates to enter.</p>}
      <dialog ref={dialogRef} className="exam-datetime-dialog" aria-labelledby={headingId} onClose={() => setOpened(false)} onClick={(event) => {
        if (event.target !== event.currentTarget) return
        const rect = event.currentTarget.getBoundingClientRect()
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close()
      }}>
        {opened && <>
          <header className="exam-datetime-dialog__heading">
            <div><h2 id={headingId}>{displayLabel}</h2><p>{entryDeadline ? 'Choose a deadline after the scheduled start so candidates have time to enter.' : 'Choose a date and local time.'}</p></div>
            <button type="button" className="exam-datetime__icon-button" aria-label="Close date picker" onClick={close}><RiCloseLine size={20} /></button>
          </header>
          <div className="exam-calendar__navigation">
            <button type="button" className="exam-datetime__icon-button" aria-label="Previous month" onClick={() => moveMonth(-1)}><RiArrowLeftSLine size={20} /></button>
            <strong aria-live="polite">{month.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}</strong>
            <button type="button" className="exam-datetime__icon-button" aria-label="Next month" onClick={() => moveMonth(1)}><RiArrowRightSLine size={20} /></button>
          </div>
          <div className="exam-calendar" role="group" aria-label="Choose date">
            {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => <span className="exam-calendar__weekday" key={day} aria-hidden="true">{day}</span>)}
            {Array.from({ length: firstDay }, (_, index) => <span key={`empty-${index}`} />)}
            {Array.from({ length: dayCount }, (_, index) => {
              const date = new Date(month.getFullYear(), month.getMonth(), index + 1, 12)
              const key = dateKey(date)
              return <button type="button" key={key} aria-label={dateLabel(date)} aria-pressed={selectedDate === key} aria-current={today === key ? 'date' : undefined} disabled={Boolean(effectiveMin && key < effectiveMin.slice(0, 10))} onClick={() => setDraft(`${key}T${hours}:${minutes}`)}>{index + 1}</button>
            })}
          </div>
          <div className="exam-datetime__time">
            <span><RiTimeLine size={18} aria-hidden="true" /> Time <small>24-hour</small></span>
            <SelectControl label={`${displayLabel} hour`} value={hours} options={HOURS} onChange={(hour) => changeTime(hour, minutes)} />
            <span aria-hidden="true">:</span>
            <SelectControl label={`${displayLabel} minute`} value={minutes} options={MINUTES} onChange={(minute) => changeTime(hours, minute)} />
          </div>
          <p id={helpId} className={`exam-datetime__hint${tooEarly ? ' is-error' : ''}`} role={tooEarly ? 'alert' : undefined}>
            {tooEarly ? `Choose a time on or after ${new Date(effectiveMin).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}.` : 'Times use this device’s local timezone.'}
          </p>
          <footer className="exam-datetime-dialog__actions">
            <button type="button" className="exam-text-action" onClick={() => { onChange(''); close() }}>Clear</button>
            <button type="button" className="teacher-secondary-action" onClick={close}>Cancel</button>
            <button type="button" className="teacher-primary-action" disabled={!draft || tooEarly} aria-describedby={helpId} onClick={() => { onChange(draft); close() }}>Apply</button>
          </footer>
        </>}
      </dialog>
    </div>
  )
}
