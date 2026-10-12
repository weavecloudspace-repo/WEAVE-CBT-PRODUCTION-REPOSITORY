import { useCallback, useEffect, useRef, useState } from 'react'

export const AI_PAGE_SIZE = 20

// Like useAdminData/useTeacherAIQuota, server state is refreshed rather than
// optimistically edited. A generation guard prevents stale requests winning.
export function useAdminAIData(api, status, requestPage, purchasePage, view = 'usage') {
  const [data, setData] = useState({})
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(true)
  const latest = useRef(0)
  const key = `${view}:${status}:${requestPage}:${purchasePage}`
  const load = useCallback(async () => {
    const generation = ++latest.current
    const queries = {
      summary: () => api.getAIQuotaSummary(),
      actors: () => api.listAIActorBalances(),
      ...(view === 'requests' ? { requests: () => api.listAIQuotaRequests({ ...(status === 'all' ? {} : { status }), offset: requestPage * AI_PAGE_SIZE, limit: AI_PAGE_SIZE }) } : {}),
      ...(view === 'purchases' ? { purchases: () => api.listAICreditPurchases({ offset: purchasePage * AI_PAGE_SIZE, limit: AI_PAGE_SIZE }) } : {}),
    }
    const keys = Object.keys(queries)
    const results = await Promise.allSettled(Object.values(queries).map((query) => query()))
    if (generation !== latest.current) return
    const snapshot = { key, source: api }
    const failures = {}
    results.forEach((result, index) => {
      const key = keys[index]
      if (result.status === 'fulfilled') snapshot[key] = result.value
      else failures[key] = result.reason.userMessage || `Unable to load AI ${key}. Refresh to try again.`
    })
    setData(snapshot)
    setErrors(failures)
    setLoading(false)
  }, [api, status, requestPage, purchasePage, key, view])
  const refresh = useCallback(() => { setLoading(true); return load() }, [load])

  useEffect(() => {
    void load()
    const onFocus = () => { void refresh() }
    window.addEventListener('focus', onFocus)
    return () => {
      latest.current += 1
      window.removeEventListener('focus', onFocus)
    }
  }, [load, refresh])

  const current = data.key === key && data.source === api
  return { ...(current ? data : {}), errors: current ? errors : {}, loading: loading || !current, refresh }
}
