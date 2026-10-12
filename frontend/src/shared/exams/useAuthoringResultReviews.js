import { useEffect, useState } from 'react'

// Missing or failed review data never grants revision eligibility.
export function useAuthoringResultReviews(gateway, exams, enabled = true) {
  const [state, setState] = useState({ source: null, reviews: [], error: '' })
  useEffect(() => {
    if (!enabled || !exams.some((exam) => exam.status === 'closed')) return undefined
    let cancelled = false
    gateway.results.listResultReviewSets()
      .then((payload) => {
        if (!cancelled) setState({ source: exams, reviews: payload?.reviews || [], error: '' })
      })
      .catch(() => {
        if (!cancelled) setState({ source: exams, reviews: [], error: 'Result decisions could not be loaded. Reload this page to check reconduct eligibility.' })
      })
    return () => { cancelled = true }
  }, [gateway, exams, enabled])
  return enabled && state.source === exams ? state : { reviews: [], error: '' }
}
