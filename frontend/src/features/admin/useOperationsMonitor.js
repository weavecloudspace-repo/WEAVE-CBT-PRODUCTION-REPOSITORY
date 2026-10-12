import { useEffect, useState } from 'react'

// Read every page before reporting totals; the monitoring endpoint is paginated.
export async function loadAttemptSnapshot(listAttempts, examId, signal) {
  const rows = new Map()
  let offset = 0
  let total
  do {
    const page = await listAttempts(examId, { offset, limit: 200 }, { signal })
    if (signal.aborted) return []
    if (!Array.isArray(page?.attempts) || !Number.isFinite(page.total)) {
      throw new Error('Invalid monitoring response')
    }
    total = page.total
    if (!page.attempts.length && offset < total) throw new Error('Incomplete monitoring response')
    page.attempts.forEach((attempt) => rows.set(attempt.id, attempt))
    offset += page.attempts.length
  } while (offset < total)
  return [...rows.values()]
}

export function useOperationsMonitor(examId, listAttempts) {
  const [snapshot, setSnapshot] = useState(null)
  useEffect(() => {
    if (!examId || !listAttempts) return undefined
    const controller = new AbortController()
    let timer
    const refresh = async () => {
      try {
        if (document.visibilityState === 'visible') {
          const attempts = await loadAttemptSnapshot(listAttempts, examId, controller.signal)
          if (!controller.signal.aborted) setSnapshot({ examId, attempts, updatedAt: new Date(), error: '' })
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setSnapshot((previous) => ({
            examId,
            attempts: previous?.examId === examId ? previous.attempts : [],
            updatedAt: previous?.examId === examId ? previous.updatedAt : null,
            error: error.userMessage || 'Candidate monitoring could not refresh. Retrying automatically.',
          }))
        }
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(refresh, 10000)
      }
    }
    void refresh()
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [examId, listAttempts])
  if (snapshot && snapshot.examId === examId) return snapshot
  return { attempts: [], updatedAt: null, error: '', loading: Boolean(examId && listAttempts) }
}
