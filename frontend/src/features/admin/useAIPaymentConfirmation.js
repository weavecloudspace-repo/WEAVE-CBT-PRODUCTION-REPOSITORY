import { useEffect, useState } from 'react'

// Verification stays on the server, where webhook and browser confirmations
// share the same idempotent credit settlement. Never infer success from a tab
// closing or a checkout link being opened.
export function useAIPaymentConfirmation(api, purchases, onSettled) {
  const pendingKey = JSON.stringify((purchases?.items || [])
    .filter((purchase) => purchase.status === 'pending')
    .map(({ reference }) => reference).sort())
  const [state, setState] = useState({ key: '', phase: 'idle' })

  useEffect(() => {
    const pending = new Set(JSON.parse(pendingKey))
    if (!pending.size) return
    let disposed = false
    let running = false
    let timer
    let deadline = Date.now() + 5 * 60_000
    let delay = 15_000
    const controller = new AbortController()
    const update = (phase) => { if (!disposed) setState({ key: pendingKey, phase }) }
    const check = async () => {
      if (disposed || running || document.visibilityState === 'hidden') return
      clearTimeout(timer)
      running = true
      update('checking')
      let changed = false
      let unavailable = false
      try {
        for (const reference of pending) {
          if (disposed) break
          try {
            const result = await api.verifyAICreditPurchase(reference, { signal: controller.signal })
            if (disposed) return
            if (result.status !== 'pending') {
              pending.delete(reference)
              changed = true
            }
          } catch (error) {
            if (disposed) return
            // The cloud verification endpoint rejects unfinished payments.
            // A rejected check is never evidence that payment succeeded.
            unavailable = true
            if ([401, 403, 404].includes(error.status)) pending.delete(reference)
          }
        }
        if (changed && !disposed) await onSettled()
      } finally {
        running = false
        if (!disposed) {
          const expired = Date.now() >= deadline
          update(!pending.size ? (unavailable ? 'unavailable' : 'idle') : expired ? 'paused' : 'waiting')
          if (pending.size && !expired) {
            timer = setTimeout(() => void check(), delay)
            delay = Math.min(delay * 2, 60_000)
          }
        }
      }
    }
    const resume = () => {
      if (document.visibilityState === 'hidden') return
      deadline = Date.now() + 5 * 60_000
      delay = 15_000
      void check()
    }
    void check()
    window.addEventListener('focus', resume)
    document.addEventListener('visibilitychange', resume)
    return () => {
      disposed = true
      controller.abort()
      clearTimeout(timer)
      window.removeEventListener('focus', resume)
      document.removeEventListener('visibilitychange', resume)
    }
  }, [api, pendingKey, onSettled])

  return state.key === pendingKey ? state.phase : 'idle'
}
