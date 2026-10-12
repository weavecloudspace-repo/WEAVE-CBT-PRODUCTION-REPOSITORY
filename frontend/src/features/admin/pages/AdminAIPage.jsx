import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../../shared/icons/Icon'
import { Panel, SelectControl, StatusBadge } from '../../../shared/ui'
import { useToast } from '../../../shared/ui/useToast'
import { AI_PAGE_SIZE, useAdminAIData } from '../useAdminAIData'
import { useAIPaymentConfirmation } from '../useAIPaymentConfirmation'
import '../admin-ai.css'

const date = (value) => new Date(value).toLocaleString()
const money = (kobo, currency = 'NGN') => new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(kobo / 100)
const positiveInteger = (value) => Number.isSafeInteger(Number(value)) && Number(value) > 0
const statusTone = (status) => status === 'success' || status === 'approved' ? 'success' : status === 'pending' ? 'warning' : 'neutral'

export function AdminAIPage({ api, requestsPage = false, purchasesPage = false, onNavigate }) {
  const [status, setStatus] = useState('pending')
  const [requestPage, setRequestPage] = useState(0)
  const [purchasePage, setPurchasePage] = useState(0)
  const [dialog, setDialog] = useState(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const lock = useRef(false)
  const model = useAdminAIData(api, status, requestPage, purchasePage, requestsPage ? 'requests' : purchasesPage ? 'purchases' : 'usage')
  const { showSuccess, showError, showInfo } = useToast()
  const { summary, actors, requests, purchases, loading, errors, refresh } = model
  const paymentPhase = useAIPaymentConfirmation(api, purchases, refresh)
  const weeklyUsed = actors?.items.reduce((sum, actor) => sum + actor.weekly_used_credits, 0)
  const weeklyAvailable = actors?.items.reduce((sum, actor) => sum + actor.weekly_available_credits, 0)

  // Empty pages can occur when the last pending row is reviewed elsewhere.
  if (!loading && requests && requestPage > 0 && requestPage * AI_PAGE_SIZE >= requests.total) setRequestPage(Math.max(0, Math.ceil(requests.total / AI_PAGE_SIZE) - 1))

  const mutate = async (operation, successMessage) => {
    if (lock.current) return false
    lock.current = true
    setBusy(true)
    setActionError('')
    try {
      const result = await operation()
      if (successMessage) showSuccess(successMessage)
      return result
    } catch (error) {
      const message = error.userMessage || 'We could not confirm this action. Refresh the latest state before trying again.'
      setActionError(message)
      showError(message)
      return false
    } finally {
      // Reconcile even on conflicts or ambiguous network failures. Weave alone
      // decides whether a request or payment has already been processed.
      await refresh()
      setBusy(false)
      lock.current = false
    }
  }

  const review = async (credits, note) => {
    const selected = dialog
    await mutate(() => selected.kind === 'approve'
      ? api.approveAIQuotaRequest(selected.item.id, { approved_credits: credits, note: note || null })
      : selected.kind === 'allocate'
        ? api.allocateAICredits({ recipient_actor_id: selected.item.actor_id, recipient_actor_type: selected.item.actor_type, credits })
        : api.rejectAIQuotaRequest(selected.item.id, { note: note || null }),
    selected.kind === 'reject' ? 'Credit request denied.' : 'Credits allocated successfully.')
    setDialog(null)
  }

  const verify = async (purchase) => {
    const result = await mutate(() => api.verifyAICreditPurchase(purchase.reference))
    if (result) {
      if (result.status === 'success') showSuccess('Payment verified. Tenant credits refreshed.')
      else showInfo(`Payment status: ${result.status}. Credits are added only after successful payment.`)
    }
  }

  const openDialog = (kind, item) => { setActionError(''); setDialog({ kind, item }) }
  return <div className="teacher-reference-page admin-ai-page" aria-busy={loading || busy}>
    <div className="teacher-page-heading">
      <div><div className="teacher-page-title-line"><span className="teacher-page-title-icon"><Icon name="ai" size={27} /></span><h1>{requestsPage ? 'Credit Requests' : purchasesPage ? 'AI Credit Purchases' : 'AI Usage'}</h1></div><p>{requestsPage ? 'Review staff requests and allocate credits from the school balance.' : purchasesPage ? 'Purchase credits for your school and track payments.' : 'Monitor staff usage and allocate AI credits.'}</p></div>
      <div className="admin-ai-actions">
        <button className="teacher-secondary-action" disabled={loading || busy} onClick={() => void refresh()}><Icon name="sync" size={16} />Refresh</button>
        {requestsPage || purchasesPage ? <button className="teacher-secondary-action" disabled={busy} onClick={() => onNavigate('ai-usage')}><Icon name="back" size={16} />Back to AI Usage</button> : <button className="teacher-secondary-action" disabled={busy} onClick={() => onNavigate('ai-credit-requests')}>Credit Requests <span className="admin-ai-count">{loading ? '…' : summary?.pending_request_count ?? '—'}</span></button>}
        {!purchasesPage && <button className="teacher-secondary-action" disabled={busy} onClick={() => onNavigate('ai-credit-purchases')}>Purchase history</button>}
        <button className="teacher-primary-action" disabled={busy} onClick={() => openDialog('purchase')}><Icon name="plus" size={16} />Purchase Credits</button>
      </div>
    </div>
    {actionError && <p role="alert" className="admin-ai-error">{actionError}</p>}
    {Object.entries(errors).map(([key, message]) => <p role="alert" className="admin-ai-error" key={key}>{message}</p>)}
    {loading && <p role="status">Loading AI credits…</p>}
    {!loading && summary && <section className={`admin-ai-summary${requestsPage || purchasesPage ? ' admin-ai-summary--compact' : ''}`} aria-label="Tenant AI credit summary">
      <div className="admin-ai-reserve">
        <span className="admin-ai-reserve__icon"><Icon name="credits" size={24} /></span>
        <div><span>School credit balance</span><strong>{summary.tenant_reserve_credits.toLocaleString()}</strong><p>Available to allocate to staff</p></div>
        {requestsPage && <span className="admin-ai-reserve__note" role="status">{summary.pending_request_count} pending credit requests</span>}
      </div>
      {!requestsPage && !purchasesPage && <dl className="admin-ai-summary-stats">
        <div><dt>Weekly credits used</dt><dd>{weeklyUsed?.toLocaleString() ?? '—'}</dd><span>Across {summary.quota_actor_count} staff accounts</span></div>
        <div><dt>Staff extra balance</dt><dd>{summary.personal_extra_balance_total.toLocaleString()}</dd><span>{summary.personal_extra_reserved_total.toLocaleString()} reserved for ongoing work</span></div>
        <div><dt>Weekly credits left</dt><dd>{weeklyAvailable?.toLocaleString() ?? '—'}</dd><span>Available to staff this week</span></div>
      </dl>}
      {!requestsPage && !purchasesPage && actors && <div className="admin-ai-summary-meter"><CreditMeter label="Staff weekly usage" used={weeklyUsed} available={weeklyAvailable} compact /></div>}
    </section>}
    {requestsPage ? <Panel title="Credit requests" action={<SelectControl label="Request status" value={status} options={['pending', 'approved', 'rejected', 'cancelled', 'all'].map((value) => ({ value, label: value === 'all' ? 'All statuses' : value[0].toUpperCase() + value.slice(1) }))} onChange={(value) => { setStatus(value); setRequestPage(0) }} />}>
      {!loading && requests && <>
        <DataTable label="Credit requests" headings={['Staff member', 'Requested', 'Approved', 'Requested on', 'Status', 'Admin note', 'Actions']} empty={!requests.items.length}>
          {requests.items.map((item) => <tr key={item.id}><td><strong>{item.requester_name || item.requester_email || 'Staff member'}</strong>{item.requester_name && <small>{item.requester_email}</small>}</td><td>{item.requested_credits}</td><td>{item.approved_credits ?? '—'}</td><td>{date(item.created_at)}</td><td><StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge></td><td>{item.admin_note || '—'}</td><td>{item.status === 'pending' && <div className="admin-ai-actions"><button className="teacher-secondary-action" disabled={busy || !summary} onClick={() => openDialog('approve', item)}>Approve</button><button className="teacher-secondary-action" disabled={busy} onClick={() => openDialog('reject', item)}>Deny</button></div>}</td></tr>)}
        </DataTable>
        <Pagination page={requestPage} total={requests.total} onChange={setRequestPage} disabled={busy} />
      </>}
    </Panel> : purchasesPage ? <Panel title="Payment history">
        <p>Complete payment in the secure checkout. Your school balance updates after payment is confirmed.</p>
        {paymentPhase !== 'idle' && <p className="admin-ai-payment-status" role="status">{paymentPhase === 'paused' ? 'Payment is still awaiting confirmation. Return after completing checkout to resume automatic checks, or check its status below.' : paymentPhase === 'unavailable' ? 'Automatic confirmation is unavailable for this payment. Refresh the history or check its status below.' : 'Checking pending payments automatically. You can continue using the dashboard.'}</p>}
        {!loading && purchases && <>
          <DataTable label="Credit purchases" headings={['Date', 'Credits', 'Amount', 'Reference', 'Status', 'Actions']} empty={!purchases.items.length}>
            {purchases.items.map((item) => <tr key={item.id}><td>{date(item.created_at)}</td><td>{item.credits}</td><td>{money(item.amount_kobo)}</td><td>{item.reference}</td><td><StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge></td><td>{item.status === 'pending' && <button className="teacher-secondary-action" disabled={busy || paymentPhase === 'checking'} onClick={() => void verify(item)}>Check status</button>}</td></tr>)}
          </DataTable>
          <Pagination page={purchasePage} total={purchases.total} onChange={setPurchasePage} disabled={busy} />
        </>}
      </Panel> : actors && <StaffCreditDirectory actors={actors.items} busy={busy || loading || !summary} onAllocate={(item) => openDialog('allocate', item)} />}
    {dialog && (dialog.kind === 'purchase' ? <PurchaseDialog api={api} onClose={() => setDialog(null)} onCheckout={() => { setDialog(null); setPurchasePage(0); if (!purchasesPage) onNavigate('ai-credit-purchases') }} mutate={mutate} busy={busy} /> : <ReviewDialog selection={dialog} reserve={summary?.tenant_reserve_credits} busy={busy} onClose={() => setDialog(null)} onSubmit={review} />)}
  </div>
}

function CreditMeter({ label, used, available, compact = false }) {
  // Actor balances expose used and available amounts, not the full weekly cap
  // or reserved weekly credits. Show that known split without inventing a cap.
  const knownCredits = used + available
  return <div className="admin-ai-meter">
    <div><span>{label}</span><strong>{compact ? `${used.toLocaleString()} used · ${available.toLocaleString()} left` : `${available} available`}</strong></div>
    <progress aria-label={label} aria-valuetext={`${used} used; ${available} available`} value={used} max={Math.max(1, knownCredits)} />
    {!compact && <div className="admin-ai-meter__legend"><span><i />{used} used</span><span>{knownCredits === 0 ? 'No weekly credits available' : `${available} left this week`}</span></div>}
  </div>
}

function StaffCreditDirectory({ actors, busy, onAllocate }) {
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('all')
  const needle = search.trim().toLocaleLowerCase()
  const filtered = actors.filter((actor) => (role === 'all' || actor.actor_type === role) && `${actor.display_name} ${actor.email || ''}`.toLocaleLowerCase().includes(needle))
  return <section className="admin-ai-directory" aria-label="Staff credit balances">
    <div className="admin-ai-section-heading"><div><span className="admin-ai-eyebrow">YOUR TEAM</span><h2>Staff credits</h2><p>Find someone and allocate credits directly. No request needed.</p></div><span className="admin-ai-directory__count" role="status">{filtered.length} of {actors.length} staff</span></div>
    <div className="admin-ai-directory__filters">
      <label className="teacher-search-control"><Icon name="search" size={18} /><input type="search" aria-label="Search staff" placeholder="Search by name or email…" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <SelectControl label="Staff role" value={role} onChange={setRole} options={[{ value: 'all', label: 'All staff' }, { value: 'teacher', label: 'Teachers' }, { value: 'tenant_admin', label: 'Administrators' }]} />
    </div>
    {filtered.length ? <div className="admin-ai-staff-list">{filtered.map((actor) => <article className="admin-ai-staff-row" key={actor.quota_account_id} aria-label={`${actor.display_name} credits`}>
      <header><span className="admin-ai-avatar">{(actor.display_name || actor.email || '?').trim().slice(0, 1).toUpperCase()}</span><div><h3>{actor.display_name || actor.email}</h3>{actor.email !== actor.display_name && <p>{actor.email}</p>}<span className="admin-ai-staff-role">{actor.actor_type === 'tenant_admin' ? 'Administrator' : 'Teacher'}</span></div></header>
      <CreditMeter label="Weekly usage" used={actor.weekly_used_credits} available={actor.weekly_available_credits} />
      <div className="admin-ai-staff-totals"><div><span>Extra available</span><strong>{actor.extra_available_credits}</strong></div><div><span>Total available</span><strong>{actor.total_available_credits}</strong></div></div>
      <button className="teacher-secondary-action" disabled={busy} onClick={() => onAllocate(actor)} aria-label={`Allocate credits to ${actor.display_name}`}><Icon name="plus" size={16} />Allocate credits</button>
    </article>)}</div> : <div className="teacher-reference-empty"><Icon name="users" size={28} /><div><strong>{actors.length ? 'No matching staff' : 'No staff credit accounts yet'}</strong><p>{actors.length ? 'Try another name, email, or role.' : 'Staff balances will appear when their AI credit accounts are available.'}</p></div>{actors.length > 0 && <button className="teacher-secondary-action" onClick={() => { setSearch(''); setRole('all') }}>Clear filters</button>}</div>}
  </section>
}

function DataTable({ label, headings, empty, children }) {
  return empty ? <div className="teacher-reference-empty"><p>No records to display.</p></div> : <div className="admin-ai-table-scroll" role="region" aria-label={label} tabIndex={0}><table><thead><tr>{headings.map((heading) => <th key={heading} scope="col">{heading}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
}

function Pagination({ page, total, onChange, disabled }) {
  return <div className="admin-ai-pagination"><span>{total} records · Page {page + 1} of {Math.max(1, Math.ceil(total / AI_PAGE_SIZE))}</span><div className="admin-ai-actions"><button className="teacher-secondary-action" disabled={disabled || page === 0} onClick={() => onChange(page - 1)}>Previous</button><button className="teacher-secondary-action" disabled={disabled || (page + 1) * AI_PAGE_SIZE >= total} onClick={() => onChange(page + 1)}>Next</button></div></div>
}

function AIDialog({ title, busy, onClose, children }) {
  const ref = useRef(null)
  useEffect(() => { ref.current.showModal() }, [])
  return <dialog ref={ref} className="admin-ai-dialog" aria-labelledby="admin-ai-dialog-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }} onClick={(event) => { if (event.target === event.currentTarget && !busy) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose() } }}>
    <h2 id="admin-ai-dialog-title">{title}</h2>{children}
  </dialog>
}

function ReviewDialog({ selection, reserve, busy, onClose, onSubmit }) {
  const { kind, item } = selection
  const [credits, setCredits] = useState(item.requested_credits ?? '')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const title = kind === 'approve' ? 'Approve credit request' : kind === 'allocate' ? 'Allocate credits' : 'Deny credit request'
  const submit = (event) => {
    event.preventDefault()
    if (busy) return
    if (kind !== 'reject' && (!positiveInteger(credits) || reserve == null || Number(credits) > reserve)) { setError('Enter a positive whole number within the available tenant reserve.'); return }
    void onSubmit(Number(credits), note.trim())
  }
  return <AIDialog title={title} busy={busy} onClose={onClose}><form onSubmit={submit}>
    <p>{item.requester_name || item.display_name || item.requester_email || 'Staff member'}</p>
    {kind !== 'reject' && <><p>Tenant reserve: {reserve ?? 'unavailable'} credits.{kind === 'approve' && ` Requested: ${item.requested_credits}. You may choose a different allocation.`}</p><label className="admin-modal-field"><span>Credits to allocate</span><input type="number" min="1" step="1" max={reserve} required value={credits} onChange={(event) => setCredits(event.target.value)} disabled={busy} /></label></>}
    {kind !== 'allocate' && <label className="admin-modal-field"><span>Admin note (optional)</span><textarea maxLength={2000} rows={3} value={note} onChange={(event) => setNote(event.target.value)} disabled={busy} /></label>}
    {error && <p role="alert" className="admin-ai-error">{error}</p>}
    <div className="admin-modal-actions"><button type="button" className="teacher-secondary-action" disabled={busy} onClick={onClose}>Cancel</button><button className="teacher-primary-action" disabled={busy}>{busy ? 'Saving…' : kind === 'reject' ? 'Deny request' : 'Allocate credits'}</button></div>
  </form></AIDialog>
}

function PurchaseDialog({ api, busy, mutate, onClose, onCheckout }) {
  const [credits, setCredits] = useState('')
  const [quote, setQuote] = useState(null)
  const [checkout, setCheckout] = useState(null)
  const [error, setError] = useState('')
  const submit = async (event) => {
    event.preventDefault()
    if (busy) return
    if (!positiveInteger(credits)) { setError('Enter a positive whole number of credits.'); return }
    setError('')
    if (!quote) {
      const result = await mutate(() => api.quoteAICreditPurchase(Number(credits)))
      if (result) setQuote(result)
      else setError('Unable to obtain a purchase quote. Try again after checking your connection.')
    } else {
      const result = await mutate(() => api.startAICreditPurchase(quote.credits))
      if (result) {
        if (result.quote) setQuote(result.quote)
        // Only the backend creates checkout sessions; never handle card data.
        try {
          const url = new URL(result.authorization_url)
          if (url.protocol !== 'https:') throw new Error('Invalid checkout URL')
          setCheckout({ ...result, authorization_url: url.href })
        } catch { setError('The payment provider returned an invalid checkout link. Check the purchase list before retrying.'); setCheckout({ invalid: true }) }
      } else {
        setCheckout({ uncertain: true })
        setError('Checkout could not be confirmed. Close this dialog and check the purchase list before starting another purchase.')
      }
    }
  }
  return <AIDialog title="Purchase Credits" busy={busy} onClose={onClose}><form onSubmit={submit}>
    {!checkout && <label className="admin-modal-field"><span>Credits to purchase</span><input type="number" min="1" step="1" required disabled={busy} value={credits} onChange={(event) => { setCredits(event.target.value); setQuote(null) }} /></label>}
    {quote && <p>{quote.credits} credits · {money(quote.amount_kobo, quote.currency)} ({money(quote.unit_price_kobo, quote.currency)} per credit)</p>}
    {checkout?.purchase && <><p>Payment reference: {checkout.purchase.reference}. We’ll confirm your payment automatically and update your school balance.</p><a className="teacher-primary-action" href={checkout.authorization_url} target="_blank" rel="noopener noreferrer" onClick={onCheckout}>Open secure checkout</a></>}
    {error && <p role="alert" className="admin-ai-error">{error}</p>}
    <div className="admin-modal-actions"><button type="button" className="teacher-secondary-action" disabled={busy} onClick={checkout?.purchase ? onCheckout : onClose}>{checkout ? 'Done' : 'Cancel'}</button>{!checkout && <button className="teacher-primary-action" disabled={busy}>{busy ? 'Please wait…' : quote ? 'Create checkout' : 'Get purchase quote'}</button>}</div>
  </form></AIDialog>
}
