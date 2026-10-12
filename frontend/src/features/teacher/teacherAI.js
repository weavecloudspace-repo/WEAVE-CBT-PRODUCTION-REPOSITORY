import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createQuestionAIController, createQuestionAIDraftStore } from '../questions/questionAIController'

export function useTeacherAIController(gateway, actorId) {
  return useMemo(() => actorId ? createQuestionAIController({
    questionsApi: gateway.questions,
    draftStore: createQuestionAIDraftStore({ scope: actorId }),
  }) : null, [gateway.questions, actorId])
}

export function isQuotaExhausted(quota) {
  return quota?.actor_type === 'teacher'
    && quota.total_available_credits === 0
    && quota.weekly?.available_credits === 0
    && quota.extra?.available_credits === 0
    && quota.weekly?.reserved_credits === 0
    && quota.extra?.reserved_credits === 0
}

export function useTeacherAIQuota(api, { includeRequests = true } = {}) {
  const [quota, setQuota] = useState(null)
  const [requests, setRequests] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const latest = useRef(0)
  const load = useCallback(() => {
    const request = ++latest.current
    return fetchQuotaSnapshot(api, includeRequests).then((snapshot) => {
      if (request === latest.current) {
        setQuota(snapshot.quota)
        setRequests(snapshot.requests)
        setError('')
      }
      return snapshot
    }).catch((error) => {
      if (request === latest.current) {
        setQuota(null)
        setRequests(null)
        setError(error.userMessage || 'Unable to check AI credits. Refresh to try again.')
      }
      return null
    }).finally(() => {
      if (request === latest.current) setLoading(false)
    })
  }, [api, includeRequests])
  const refresh = useCallback(() => { setLoading(true); return load() }, [load])
  useEffect(() => {
    void load()
    const onFocus = () => { void refresh() }
    window.addEventListener('focus', onFocus)
    return () => { latest.current += 1; window.removeEventListener('focus', onFocus) }
  }, [load, refresh])
  return { quota, requests, error, loading, refresh, exhausted: !loading && isQuotaExhausted(quota) }
}

export function validateAIQuestion(question) {
  if (!question.prompt.trim()) return 'Write a question prompt.'
  if (question.options.length < 2) return 'Keep at least two answer options.'
  if (question.options.some((option) => !option.text?.trim() && !option.image)) return 'Every option needs text or an image.'
  const correct = question.options.filter((option) => option.is_correct).length
  if (question.question_type === 'single_choice' && correct !== 1) return 'Mark exactly one correct answer.'
  if (question.question_type === 'multiple_choice' && (correct < 2 || correct === question.options.length)) return 'Mark at least two correct answers and leave at least one incorrect answer.'
  return ''
}

async function fetchQuotaSnapshot(api, includeRequests) {
  const quota = await api.getMyAIQuota()
  const requests = []
  if (!includeRequests) return { quota, requests }
  let offset = 0
  let page
  do {
    page = await api.listMyAIQuotaRequests({ offset, limit: 100 })
    requests.push(...page.items.filter((item) => item.status === 'pending'))
    offset += page.items.length
  } while (offset < page.total && page.items.length)
  return { quota, requests }
}
