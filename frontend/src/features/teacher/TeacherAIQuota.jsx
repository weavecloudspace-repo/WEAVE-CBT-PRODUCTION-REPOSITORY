import { useState } from 'react'
import { RiRefreshLine } from '@remixicon/react'
import { isQuotaExhausted } from './teacherAI'

export function TeacherAIQuota({ model, api, onManageCredits }) {
  const [requestOpen, setRequestOpen] = useState(false)
  const [credits, setCredits] = useState(20)
  const [sending, setSending] = useState(false)
  const [message, setMessage] = useState('')
  const { quota, requests, loading, error, exhausted, refresh } = model
  const reserved = (quota?.weekly.reserved_credits || 0) + (quota?.extra.reserved_credits || 0)
  const submit = async (event) => {
    event.preventDefault()
    if (sending) return
    setSending(true)
    setMessage('')
    try {
      const current = await refresh()
      if (!isQuotaExhausted(current?.quota) || current.requests.length > 0) { setRequestOpen(false); return }
      await api.requestAICredits(Number(credits))
      setRequestOpen(false)
      setMessage('Credit request sent to your administrator.')
    } catch (error) {
      setMessage(error.userMessage || 'We could not confirm your request. Refresh before trying again.')
      setRequestOpen(false)
    } finally {
      await refresh()
      setSending(false)
    }
  }
  return <section className="teacher-ai-quota" aria-label="AI credit usage" aria-busy={loading}>
    <div className="teacher-ai-quota__heading"><strong>AI credits</strong><button type="button" className="teacher-ai-icon-button" aria-label="Refresh AI credits" disabled={loading || sending} onClick={() => void refresh()}><RiRefreshLine size={16} /></button></div>
    {error ? <p role="alert">{error}</p> : quota ? <>
      <div className="teacher-ai-quota__balance"><strong>{quota.total_available_credits}</strong><span>available</span></div>
      <progress aria-label="Weekly credits used" value={quota.weekly.used_credits} max={Math.max(1, quota.weekly.credit_limit)} />
      <div className="teacher-ai-quota__details"><span>{quota.weekly.used_credits} / {quota.weekly.credit_limit} weekly used</span><span>{quota.extra.available_credits} extra available</span></div>
      {reserved > 0 && <p>{reserved} credits reserved for ongoing requests.</p>}
      {onManageCredits && <button className="text-button" type="button" onClick={onManageCredits}>Manage AI credits</button>}
      {requests?.length > 0 && <p>Credit request pending · {requests.reduce((sum, item) => sum + item.requested_credits, 0)} credits requested</p>}
      {exhausted && requests?.length === 0 && !requestOpen && <button className="text-button" type="button" disabled={sending} onClick={() => setRequestOpen(true)}>Request more credits</button>}
      {exhausted && requests?.length === 0 && requestOpen && <form onSubmit={submit} className="teacher-ai-quota__request"><label>Credits to request<input type="number" min="1" max="100000" required value={credits} onChange={(event) => setCredits(event.target.value)} /></label><button type="submit" className="teacher-secondary-action" disabled={sending}>{sending ? 'Sending…' : 'Send request'}</button></form>}
    </> : <p>Checking your credits…</p>}
    {message && <p role="status">{message}</p>}
  </section>
}
