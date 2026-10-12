import { useCallback } from 'react'

const listeners = new Set()
let notifications = []
const publish = () => listeners.forEach((listener) => listener())

export const toastBus = {
  subscribe(listener) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  getSnapshot: () => notifications,
  remove(id) {
    const next = notifications.filter((toast) => toast.id !== id)
    if (next.length === notifications.length) return
    notifications = next
    publish()
  },
  dismiss(id) {
    const target = notifications.find((toast) => toast.id === id)
    if (!target) return
    notifications = notifications.filter((toast) => toast.message !== target.message || toast.type !== target.type)
    publish()
  },
  clear() {
    notifications = []
    publish()
  },
  show(message, type = 'info', options = {}) {
    const normalizedMessage = typeof message === 'string' ? message.trim() : message
    if (!normalizedMessage) return null
    const id = options.id || `${type}:${normalizedMessage}`
    notifications = [...notifications.filter((toast) => toast.id !== id), {
      id,
      message: normalizedMessage,
      type,
      duration: type === 'error' ? 0 : options.duration ?? 4000,
      revision: Date.now(),
    }]
    publish()
    return id
  },
  info(message, options) {
    return toastBus.show(message, 'info', options)
  },
  success(message, options) {
    return toastBus.show(message, 'success', options)
  },
  warning(message, options) {
    return toastBus.show(message, 'warning', options)
  },
  error(message, options) {
    return toastBus.show(message, 'error', options)
  },
}

export function useToast() {
  const showToast = useCallback((message, type = 'info', options = {}) => toastBus.show(message, type, options), [])
  const showSuccess = useCallback((message, options = {}) => toastBus.success(message, options), [])
  const showError = useCallback((message, options = {}) => toastBus.error(message, options), [])
  const showWarning = useCallback((message, options = {}) => toastBus.warning(message, options), [])
  const showInfo = useCallback((message, options = {}) => toastBus.info(message, options), [])

  return { showToast, showSuccess, showError, showWarning, showInfo }
}
