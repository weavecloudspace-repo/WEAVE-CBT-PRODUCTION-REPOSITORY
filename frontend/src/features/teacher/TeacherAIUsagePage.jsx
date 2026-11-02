import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Icon } from '../../shared/icons/Icon'
import { Panel, StatusBadge } from '../../shared/ui'
import { useToast } from '../../shared/ui/useToast'
import { useAIPaymentConfirmation } from '../admin/useAIPaymentConfirmation'
import { isQuotaExhausted } from './teacherAI'
import '../admin/admin-ai.css'
import './teacher-ai-usage.css'

const PAGE_SIZE = 20
const numeric = (value) => Number(value || 0).toLocaleString()
const validCredits = (value) => Number.isSafeInteger(Number(value)) && Number(value) > 0
const money = (value, currency = 'NGN') =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(Number(value || 0) / 100)
const date = (value) => value ? new Date(value).toLocaleString() : '—'
const tone = (status) => ['success', 'approved'].includes(status) ? 'success' : status === 'pending' ? 'warning' : 'neutral'
const err = (error) => error?.userMessage || 'The cloud could not confirm this action. Refresh and try again.'

export function TeacherAIUsagePage({ api }) {
  const { showError, showSuccess } = useToast()
  const [tab, setTab] = useState('overview')
  const [page, setPage] = useState(0)
  const [quota, setQuota] = useState(null)
  const [requests, setRequests] = useState(null)
  const [purchases, setPurchases] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dialog, setDialog] = useState(false)
  const [credits, setCredits] = useState('20')
  const [quote, setQuote] = useState(null)
  const [checkout, setCheckout] = useState(null)
  const [requestAmount, setRequestAmount] = useState('20')
  const generation = useRef(0)
  const lock = useRef(false)

  const refresh = useCallback(async () => {
    const version = ++generation.current
    setLoading(true)
    const tasks = await Promise.allSettled([
      api.getMyAIQuota(),
      api.listMyAIQuotaRequests({ offset: 0, limit: 100 }),
      api.listTeacherAICreditPurchases({ offset: page * PAGE_SIZE, limit: PAGE_SIZE }),
    ])
    if (version !== generation.current) return
    const problems = []
    const setters = [setQuota, setRequests, setPurchases]
    tasks.forEach((result, index) => {
      if (result.status === 'fulfilled') setters[index](result.value)
      else {
        problems.push(err(result.reason))
        setters[index](null)
      }
    })
    setError(problems.join(' · '))
    setLoading(false)
  }, [api, page])

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh() }, 0)
    return () => {
      window.clearTimeout(timer)
      generation.current += 1
    }
  }, [refresh])

  const verifyApi = useMemo(() => ({
    verifyAICreditPurchase: (reference, options) =>
      api.verifyTeacherAICreditPurchase(reference, options),
  }), [api])
  const paymentPhase = useAIPaymentConfirmation(verifyApi, purchases, refresh)
  const pending = (requests?.items || []).filter((item) => item.status === 'pending')
  const week = quota?.weekly
  const extra = quota?.extra
  const weekLimit = Math.max(1, Number(week?.credit_limit || 0))
  const reserved = Number(week?.reserved_credits || 0) + Number(extra?.reserved_credits || 0)

  const transact = async (work, successMessage) => {
    if (lock.current) return null
    lock.current = true
    setBusy(true)
    setError('')
    try {
      const result = await work()
      if (successMessage) showSuccess(successMessage)
      return result
    } catch (e) {
      setError(err(e))
      showError(err(e))
      return null
    } finally {
      lock.current = false
      setBusy(false)
      await refresh()
    }
  }
  const closeDialog = () => {
    if (busy) return
    setDialog(false)
    setQuote(null)
    setCheckout(null)
  }
  const purchase = async (event) => {
    event.preventDefault()
    if (busy || checkout || !validCredits(credits)) return
    if (!quote) {
      const next = await transact(() => api.quoteTeacherAICredits(Number(credits)))
      if (next && next.credits === Number(credits)) setQuote(next)
    } else {
      const result = await transact(() => api.checkoutTeacherAICredits(quote.credits))
      if (!result) return
      try {
        const url = new URL(result.authorization_url)
        if (url.protocol !== 'https:') throw Error('Unsafe checkout URL')
        setCheckout({ url: url.href, reference: result.purchase?.reference })
      } catch {
        setError('Checkout URL could not be verified. Check payment history before trying again.')
      }
    }
  }
  const requestCredits = async (event) => {
    event.preventDefault()
    if (!validCredits(requestAmount) || pending.length || !isQuotaExhausted(quota)) return
    await transact(() => api.requestAICredits(Number(requestAmount)), 'Your credit request has been submitted.')
  }
  const verifyPurchase = async (purchaseItem) => {
    await transact(() => api.verifyTeacherAICreditPurchase(purchaseItem.reference))
  }

  return <div className="teacher-reference-page admin-ai-page teacher-ai-usage-page" aria-busy={loading || busy}>
    <div className="teacher-page-heading">
      <div>
        <div className="teacher-page-title-line"><span className="teacher-page-title-icon"><Icon name="ai" size={27} /></span><h1>AI Usage</h1></div>
        <p>Monitor your question-generation credits and manage personal purchases.</p>
      </div>
      <div className="admin-ai-actions">
        <button className="teacher-secondary-action" disabled={busy || loading} onClick={() => void refresh()}><Icon name="sync" size={16} /> Refresh</button>
        <button className="teacher-primary-action" disabled={busy} onClick={() => { setQuote(null); setCheckout(null); setDialog(true) }}><Icon name="plus" size={16} /> Buy credits</button>
      </div>
    </div>
    {error && <p role="alert" className="admin-ai-error">{error}</p>}
    {loading && <p role="status">Loading your AI usage…</p>}
    {quota && <section className="admin-ai-summary teacher-ai-summary" aria-label="Teacher AI credit summary">
      <div className="admin-ai-reserve">
        <span className="admin-ai-reserve__icon"><Icon name="credits" size={24} /></span>
        <div><span>Available credits</span><strong>{numeric(quota.total_available_credits)}</strong><p>Weekly and personal credits combined</p></div>
      </div>
      <dl className="admin-ai-summary-stats">
        <div><dt>Weekly used</dt><dd>{numeric(week?.used_credits)}</dd><span>Of {numeric(week?.credit_limit)} weekly credits</span></div>
        <div><dt>Weekly remaining</dt><dd>{numeric(week?.available_credits)}</dd><span>Resets with your weekly allocation</span></div>
        <div><dt>Personal extras</dt><dd>{numeric(extra?.available_credits)}</dd><span>{numeric(reserved)} credits currently reserved</span></div>
      </dl>
      <div className="admin-ai-summary-meter">
        <div className="admin-ai-meter">
          <div><span>Weekly credit usage</span><strong>{numeric(week?.used_credits)} of {numeric(week?.credit_limit)} used</strong></div>
          <progress value={Number(week?.used_credits || 0)} max={weekLimit} aria-label="Weekly AI credits used" />
        </div>
      </div>
    </section>}
    <nav className="teacher-ai-usage-tabs" aria-label="AI usage sections">
      {[['overview', 'Overview'], ['requests', 'Credit requests'], ['purchases', 'Purchase history']].map(([key, label]) =>
        <button key={key} type="button" aria-current={tab === key ? 'page' : undefined}
          onClick={() => setTab(key)}>{label}{key === 'requests' && pending.length ? ` (${pending.length})` : ''}</button>)}
    </nav>
    {tab === 'overview' && <div className="teacher-ai-usage-panels">
      <Panel title="Your credits">
        <p>Your AI balance is shared across WEAVE CBT and WEAVE TMA. Purchases add credits to your personal balance; administrators manage the school reserve separately.</p>
        {pending.length > 0 && <p className="teacher-ai-usage-note">{pending.length} credit request(s) awaiting approval.</p>}
        {isQuotaExhausted(quota) && !pending.length && <form className="teacher-ai-request-form" onSubmit={requestCredits}>
          <label>Credits to request <input type="number" value={requestAmount} min="1" step="1" onChange={(event) => setRequestAmount(event.target.value)} /></label>
          <button type="submit" className="teacher-secondary-action" disabled={busy || !validCredits(requestAmount)}>Request credits</button>
        </form>}
        <button type="button" className="teacher-secondary-action" onClick={() => setTab('purchases')}>View purchase history</button>
      </Panel>
      <Panel title="Getting started">
        <p>AI generation uses the credits shown above. Check each generated answer before adding it to a question bank.</p>
        <p>Use Buy credits to get a quote before opening the secure checkout. Credits are added only after the payment provider confirms payment.</p>
      </Panel>
    </div>}
    {tab === 'requests' && <Panel title="Credit requests">
      <div className="admin-ai-table-scroll" role="region" aria-label="My AI credit requests" tabIndex={0}>
        <table><thead><tr><th>Requested</th><th>Approved</th><th>Date</th><th>Status</th><th>Notes</th></tr></thead>
          <tbody>{(requests?.items || []).map((item) => <tr key={item.id}>
            <td>{numeric(item.requested_credits)}</td><td>{item.approved_credits == null ? '—' : numeric(item.approved_credits)}</td>
            <td>{date(item.created_at)}</td><td><StatusBadge tone={tone(item.status)}>{item.status}</StatusBadge></td><td>{item.admin_note || '—'}</td>
          </tr>)}</tbody></table>
      </div>
      {requests && !requests.items.length && <p>No credit requests yet.</p>}
      {Number(requests?.total || 0) > (requests?.items?.length || 0) && <p className="teacher-ai-usage-note">Showing the first 100 requests.</p>}
    </Panel>}
    {tab === 'purchases' && <Panel title="Personal purchase history">
      {paymentPhase !== 'idle' && <p role="status" className="teacher-ai-usage-note">
        {paymentPhase === 'paused' ? 'Payment confirmation paused. Return to this page to retry.' : paymentPhase === 'unavailable' ? 'Automatic confirmation unavailable. Check purchase status below.' : 'Checking pending payments securely…'}
      </p>}
      <div className="admin-ai-table-scroll" role="region" aria-label="My AI purchases" tabIndex={0}>
        <table><thead><tr><th>Date</th><th>Credits</th><th>Amount</th><th>Reference</th><th>Status</th><th>Action</th></tr></thead>
          <tbody>{(purchases?.items || []).map((item) => <tr key={item.id}>
            <td>{date(item.created_at)}</td><td>{numeric(item.credits)}</td><td>{money(item.amount_kobo, item.currency)}</td><td>{item.reference}</td>
            <td><StatusBadge tone={tone(item.status)}>{item.status}</StatusBadge></td>
            <td>{item.status === 'pending' && <button type="button" disabled={busy || paymentPhase === 'checking'} className="teacher-secondary-action" onClick={() => void verifyPurchase(item)}>Check status</button>}</td>
          </tr>)}</tbody></table>
      </div>
      {purchases && !purchases.items.length && <p>No purchases yet.</p>}
      {purchases && purchases.total > PAGE_SIZE && <div className="admin-ai-pagination">
        <span>{purchases.total} purchases · Page {page + 1} of {Math.ceil(purchases.total / PAGE_SIZE)}</span>
        <div className="admin-ai-actions">
          <button className="teacher-secondary-action" disabled={busy || page === 0} onClick={() => setPage(page - 1)}>Previous</button>
          <button className="teacher-secondary-action" disabled={busy || (page + 1) * PAGE_SIZE >= purchases.total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </div>}
    </Panel>}
    {dialog && <div className="teacher-ai-buy-overlay" role="presentation">
      <section role="dialog" aria-modal="true" aria-label="Buy personal AI credits" className="teacher-ai-buy-dialog">
        <h2>Buy AI credits</h2>
        <p>Credits purchased here belong to your teacher account.</p>
        <form onSubmit={(event) => void purchase(event)}>
          {!checkout && <label>Credits to purchase<input type="number" required min="1" step="1" value={credits} disabled={busy}
            onChange={(event) => { setCredits(event.target.value); setQuote(null) }} /></label>}
          {quote && <p role="status">{numeric(quote.credits)} credits · {money(quote.amount_kobo, quote.currency)} ({money(quote.unit_price_kobo, quote.currency)} per credit)</p>}
          {checkout && <div className="teacher-ai-buy-confirmation">
            <p>Checkout created. Payment reference: {checkout.reference || 'See purchase history'}.</p>
            <a className="teacher-primary-action" target="_blank" rel="noopener noreferrer" href={checkout.url} onClick={() => { closeDialog(); setTab('purchases'); setPage(0) }}>Open secure checkout</a>
          </div>}
          <div className="admin-modal-actions">
            <button type="button" className="teacher-secondary-action" disabled={busy} onClick={closeDialog}>Close</button>
            {!checkout && <button className="teacher-primary-action" disabled={busy || !validCredits(credits)} type="submit">{busy ? 'Please wait…' : quote ? 'Create checkout' : 'Get quote'}</button>}
          </div>
        </form>
      </section>
    </div>}
  </div>
}
