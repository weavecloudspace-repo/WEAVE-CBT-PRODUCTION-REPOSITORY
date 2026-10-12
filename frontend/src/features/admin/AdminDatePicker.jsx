import { useId, useRef, useState } from 'react'
import { RiCalendarLine, RiArrowDownSLine, RiArrowLeftSLine, RiArrowRightSLine, RiCloseLine } from '@remixicon/react'
import '../../shared/exams/exam-date-time-picker.css'
import './admin-date-picker.css'

const keyFor = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const labelFor = (date) => date.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })

export function AdminDatePicker({ value, onChange, label = 'Operations date', description = 'Choose a day to view its sittings.' }) {
  const dialog = useRef(null)
  const headingId = useId()
  const [month, setMonth] = useState(() => new Date(`${value}T12:00:00`))
  const [open, setOpen] = useState(false)
  const selected = new Date(`${value}T12:00:00`)
  const today = keyFor(new Date())
  const firstDay = new Date(month.getFullYear(), month.getMonth(), 1).getDay()
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const choose = (date) => { onChange(date); dialog.current.close() }
  const show = () => {
    setMonth(selected)
    setOpen(true)
    dialog.current.showModal()
  }
  return <>
    <button type="button" className="admin-ops-date" aria-label={`${label}: ${labelFor(selected)}`} aria-haspopup="dialog" aria-expanded={open} onClick={show}>
      <RiCalendarLine size={19} aria-hidden="true" />
      <span>{label}<strong>{selected.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })}</strong></span>
      <RiArrowDownSLine size={16} aria-hidden="true" />
    </button>
    <dialog ref={dialog} className="exam-datetime-dialog admin-ops-calendar" aria-labelledby={headingId} onClose={() => setOpen(false)} onClick={(event) => {
      if (event.target !== event.currentTarget) return
      const rect = event.currentTarget.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.current.close()
    }}>
      <header className="exam-datetime-dialog__heading">
        <div><h2 id={headingId}>{label}</h2><p>{description}</p></div>
        <button type="button" className="exam-datetime__icon-button" aria-label="Close date picker" onClick={() => dialog.current.close()}><RiCloseLine size={20} /></button>
      </header>
      <div className="exam-calendar__navigation">
        <button type="button" className="exam-datetime__icon-button" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><RiArrowLeftSLine size={20} /></button>
        <strong aria-live="polite">{month.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}</strong>
        <button type="button" className="exam-datetime__icon-button" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><RiArrowRightSLine size={20} /></button>
      </div>
      <div className="exam-calendar" role="group" aria-label={`Choose ${label.toLowerCase()}`}>
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => <span className="exam-calendar__weekday" key={day} aria-hidden="true">{day}</span>)}
        {Array.from({ length: firstDay }, (_, index) => <span key={`empty-${index}`} />)}
        {Array.from({ length: days }, (_, index) => {
          const date = new Date(month.getFullYear(), month.getMonth(), index + 1, 12)
          const key = keyFor(date)
          return <button type="button" key={key} aria-label={labelFor(date)} aria-pressed={value === key} aria-current={today === key ? 'date' : undefined} onClick={() => choose(key)}>{index + 1}</button>
        })}
      </div>
      <footer className="admin-ops-calendar__footer"><span>Select a date to apply</span><button type="button" className="admin-date-picker__today" onClick={() => choose(today)}>Today</button></footer>
    </dialog>
  </>
}
