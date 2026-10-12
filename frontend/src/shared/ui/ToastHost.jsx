import { useEffect, useState, useSyncExternalStore } from 'react'
import {
  RiCheckboxCircleLine,
  RiCloseLine,
  RiErrorWarningLine,
  RiInformationLine,
} from '@remixicon/react'
import { toastBus } from './useToast'
import './toast.css'

const icons = {
  info: RiInformationLine,
  success: RiCheckboxCircleLine,
  warning: RiErrorWarningLine,
  error: RiErrorWarningLine,
}

function ToastCard({ toast, onClose }) {
  const [paused, setPaused] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const ToastIcon = icons[toast.type] || icons.info

  useEffect(() => {
    if (!toast.duration || paused || leaving) return undefined
    const timeoutId = window.setTimeout(() => setLeaving(true), toast.duration)
    return () => window.clearTimeout(timeoutId)
  }, [toast.duration, toast.revision, paused, leaving])

  useEffect(() => {
    if (!leaving) return undefined
    const timeoutId = window.setTimeout(() => onClose(toast.id), 200)
    return () => window.clearTimeout(timeoutId)
  }, [leaving, onClose, toast.id])

  return (
    <div
      className={`weave-toast weave-toast--${toast.type || 'info'}${leaving ? ' is-leaving' : ''}`}
      role={toast.type === 'error' ? 'alert' : 'status'}
      aria-live={toast.type === 'error' ? 'assertive' : 'polite'}
      aria-atomic="true"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false) }}
    >
      <ToastIcon className="weave-toast__icon" size={20} aria-hidden="true" />
      <p>{toast.message}</p>
      <button type="button" onClick={() => setLeaving(true)} aria-label="Dismiss notification">
        <RiCloseLine size={17} aria-hidden="true" />
      </button>
    </div>
  )
}

export function ToastHost() {
  const toasts = useSyncExternalStore(toastBus.subscribe, toastBus.getSnapshot, toastBus.getSnapshot)
  const uniqueToasts = toasts.filter((toast, index) => toasts.findIndex((item) => item.message === toast.message && item.type === toast.type) === index)
  if (toasts.length === 0) return null
  return (
    <div className="weave-toast-host" aria-label="Notifications">
      {uniqueToasts.map((toast) => <ToastCard key={`${toast.id}:${toast.revision}`} toast={toast} onClose={toastBus.dismiss} />)}
    </div>
  )
}
