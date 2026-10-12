import { useEffect, useId, useRef, useState } from 'react'
import { RiAddLine } from '@remixicon/react'
import { Icon } from '../../shared/icons/Icon'

const actions = [
  { section: 'roster', icon: 'roster', label: 'Candidate rosters', copy: 'Review eligibility and late entry' },
  { section: 'results', icon: 'results', label: 'Review results', copy: 'Inspect completed examination results' },
  { section: 'timetable', icon: 'calendar', label: 'Timetable', copy: 'View scheduled examinations by level' },
]

export function OperationsQuickActions({ onNavigate }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  const trigger = useRef(null)
  const menuId = useId()
  useEffect(() => {
    if (!open) return undefined
    root.current.querySelector('[role="menuitem"]')?.focus()
    const dismiss = (event) => {
      if (event.type === 'keydown' && event.key === 'Escape') {
        setOpen(false)
        trigger.current.focus()
      }
      if (event.type === 'pointerdown' && !root.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', dismiss)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', dismiss)
    }
  }, [open])
  return <div className="teacher-quick-menu" ref={root} onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
  }}>
    <button ref={trigger} type="button" className="teacher-quick-menu__trigger" aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} onClick={() => setOpen((value) => !value)}><RiAddLine size={18} aria-hidden="true" /> Quick Actions</button>
    {open && <div id={menuId} className="teacher-quick-menu__dropdown" role="menu" aria-label="Operations quick actions" onKeyDown={(event) => {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const items = [...event.currentTarget.querySelectorAll('[role="menuitem"]')]
      const current = items.indexOf(document.activeElement)
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
      items[next].focus()
    }}>
      {actions.map((action) => <button key={action.section} type="button" role="menuitem" onClick={() => { setOpen(false); trigger.current.focus(); onNavigate(action.section) }}><Icon name={action.icon} size={19} /><span><strong>{action.label}</strong><small>{action.copy}</small></span></button>)}
    </div>}
  </div>
}
