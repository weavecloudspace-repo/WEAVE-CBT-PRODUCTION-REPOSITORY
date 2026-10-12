import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { AdminAIPage } from '../src/features/admin/pages/AdminAIPage'
import { parseStaffPath, pathForStaffState, staffSectionForRole } from '../src/app/staffNavigation'
import { useAdminAIData } from '../src/features/admin/useAdminAIData'

beforeAll(() => { HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') } })
afterEach(cleanup)
const request = { id: 'request-1', requester_name: 'Ada', requested_credits: 30, status: 'pending', created_at: '2026-10-02T09:00:00Z' }
function makeAPI() {
  const summary = { tenant_reserve_credits: 100, pending_request_count: 1, personal_extra_balance_total: 8, personal_extra_reserved_total: 2, quota_actor_count: 1 }
  return {
    getAIQuotaSummary: vi.fn().mockResolvedValue(summary),
    listAIActorBalances: vi.fn().mockResolvedValue({ items: [{ quota_account_id: 'quota-1', actor_id: 'actor-1', actor_type: 'teacher', display_name: 'Ada', weekly_used_credits: 7, weekly_available_credits: 3, extra_available_credits: 8, total_available_credits: 11 }], total: 1 }),
    listAIQuotaRequests: vi.fn().mockResolvedValue({ items: [request], total: 1 }),
    listAICreditPurchases: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    approveAIQuotaRequest: vi.fn(async (_id, payload) => {
      summary.tenant_reserve_credits -= payload.approved_credits
      summary.pending_request_count = 0
      return { ...request, status: 'approved' }
    }),
    rejectAIQuotaRequest: vi.fn().mockResolvedValue({ ...request, status: 'rejected' }),
    allocateAICredits: vi.fn().mockResolvedValue({}),
    quoteAICreditPurchase: vi.fn().mockResolvedValue({ credits: 50, unit_price_kobo: 100, amount_kobo: 5000, currency: 'NGN' }),
    startAICreditPurchase: vi.fn().mockResolvedValue({ authorization_url: 'https://checkout.example/session', purchase: { reference: 'ref-1' } }),
    verifyAICreditPurchase: vi.fn().mockResolvedValue({ status: 'success' }),
  }
}

describe('Admin AI management', () => {
  it('routes AI pages only within the admin role', () => {
    for (const section of ['ai-usage', 'ai-credit-requests', 'ai-credit-purchases']) {
      expect(parseStaffPath(`/admin/${section}`).staffSection).toBe(section)
      expect(pathForStaffState({ session: { role: 'admin' }, staff: { section } })).toBe(`/admin/${section}`)
      expect(staffSectionForRole('teacher', section)).toBe('overview')
    }
  })

  it('renders authoritative balances and navigates with the pending count', async () => {
    const onNavigate = vi.fn()
    render(<AdminAIPage api={makeAPI()} onNavigate={onNavigate} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Credit Requests 1' }))
    expect(onNavigate).toHaveBeenCalledWith('ai-credit-requests')
    const metrics = screen.getByRole('region', { name: 'Tenant AI credit summary' })
    expect(within(metrics).getByText('100')).toBeInTheDocument()
    expect(within(metrics).getByText('Weekly credits used')).toBeInTheDocument()
    expect(within(metrics).getByText('7')).toBeInTheDocument()
    expect(within(metrics).getByText('Weekly credits left')).toBeInTheDocument()
    expect(within(metrics).getByText('3')).toBeInTheDocument()
    expect(within(metrics).queryByText('Ideas in motion')).not.toBeInTheDocument()
  })

  it('approves a custom amount once and refreshes every affected resource', async () => {
    const api = makeAPI()
    render(<AdminAIPage api={api} requestsPage onNavigate={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve', exact: true }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Credits to allocate'), { target: { value: '12' } })
    fireEvent.change(within(dialog).getByLabelText('Admin note (optional)'), { target: { value: 'Revision' } })
    const submit = within(dialog).getByRole('button', { name: 'Allocate credits' })
    fireEvent.click(submit)
    fireEvent.click(submit)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(api.approveAIQuotaRequest).toHaveBeenCalledTimes(1)
    expect(api.approveAIQuotaRequest).toHaveBeenCalledWith('request-1', { approved_credits: 12, note: 'Revision' })
    for (const name of ['getAIQuotaSummary', 'listAIActorBalances', 'listAIQuotaRequests']) expect(api[name]).toHaveBeenCalledTimes(2)
    expect(api.listAICreditPurchases).not.toHaveBeenCalled()
    expect(screen.getByText('88')).toBeInTheDocument()
    expect(screen.getByText('0 pending credit requests')).toBeInTheDocument()
  })

  it('rejects invalid amounts without calling the backend', async () => {
    const api = makeAPI()
    render(<AdminAIPage api={api} requestsPage onNavigate={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve', exact: true }))
    const dialog = screen.getByRole('dialog')
    for (const value of ['0', '1.5', '101']) {
      fireEvent.change(within(dialog).getByLabelText('Credits to allocate'), { target: { value } })
      fireEvent.submit(dialog.querySelector('form'))
      expect(within(dialog).getByRole('alert')).toHaveTextContent('positive whole number')
    }
    expect(api.approveAIQuotaRequest).not.toHaveBeenCalled()
  })

  it('denies with a note and reconciles conflicting approvals', async () => {
    const api = makeAPI()
    render(<AdminAIPage api={api} requestsPage onNavigate={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Deny', exact: true }))
    fireEvent.change(screen.getByLabelText('Admin note (optional)'), { target: { value: 'Already allocated' } })
    fireEvent.click(screen.getByRole('button', { name: 'Deny request' }))
    await waitFor(() => expect(api.rejectAIQuotaRequest).toHaveBeenCalledWith('request-1', { note: 'Already allocated' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    api.approveAIQuotaRequest.mockRejectedValue({ userMessage: 'Request already resolved.' })
    fireEvent.click(screen.getByRole('button', { name: 'Approve', exact: true }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Allocate credits' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('Request already resolved.')
    expect(api.getAIQuotaSummary).toHaveBeenCalledTimes(3)
  })

  it('uses backend quote and checkout without crediting the balance locally', async () => {
    const api = makeAPI()
    render(<AdminAIPage api={api} purchasesPage onNavigate={vi.fn()} />)
    await screen.findByText('100')
    fireEvent.click(screen.getByRole('button', { name: 'Purchase Credits' }))
    fireEvent.change(screen.getByLabelText('Credits to purchase'), { target: { value: '50' } })
    fireEvent.click(screen.getByRole('button', { name: 'Get purchase quote' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create checkout' }))
    expect(await screen.findByRole('link', { name: 'Open secure checkout' })).toHaveAttribute('href', 'https://checkout.example/session')
    expect(api.quoteAICreditPurchase).toHaveBeenCalledWith(50)
    expect(api.startAICreditPurchase).toHaveBeenCalledWith(50)
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.getByText('100')).toBeInTheDocument()
  })

  it('automatically confirms pending payments and supports direct staff allocations', async () => {
    const api = makeAPI()
    const purchase = { id: 'purchase-1', reference: 'ref-1', credits: 50, amount_kobo: 5000, status: 'pending', created_at: request.created_at }
    api.listAICreditPurchases.mockResolvedValue({ items: [purchase], total: 1 })
    api.verifyAICreditPurchase.mockImplementation(async () => {
      purchase.status = 'success'
      return purchase
    })
    const { rerender } = render(<AdminAIPage api={api} purchasesPage onNavigate={vi.fn()} />)
    await waitFor(() => expect(api.getAIQuotaSummary).toHaveBeenCalledTimes(2))
    expect(api.verifyAICreditPurchase).toHaveBeenCalledWith('ref-1', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(await screen.findByText('success')).toBeInTheDocument()
    rerender(<AdminAIPage api={api} onNavigate={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Allocate credits to Ada' }))
    fireEvent.change(screen.getByLabelText('Credits to allocate'), { target: { value: '5' } })
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Allocate credits' }))
    await waitFor(() => expect(api.allocateAICredits).toHaveBeenCalledWith({ recipient_actor_id: 'actor-1', recipient_actor_type: 'teacher', credits: 5 }))
  })

  it('requests actual backend status and pagination filters', async () => {
    const api = makeAPI()
    api.listAIQuotaRequests.mockResolvedValue({ items: [request], total: 25 })
    render(<AdminAIPage api={api} requestsPage onNavigate={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }))
    await waitFor(() => expect(api.listAIQuotaRequests).toHaveBeenCalledWith({ status: 'pending', offset: 20, limit: 20 }))
    await waitFor(() => expect(screen.queryByText('Loading AI credits…')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('combobox', { name: 'Request status' }))
    fireEvent.click(screen.getByRole('option', { name: 'Rejected' }))
    await waitFor(() => expect(api.listAIQuotaRequests).toHaveBeenCalledWith({ status: 'rejected', offset: 0, limit: 20 }))
  })

  it('keeps balances usable when request loading fails and never invents a count', async () => {
    const api = makeAPI()
    api.getAIQuotaSummary.mockRejectedValue({ userMessage: 'Administrator access required.' })
    api.listAIQuotaRequests.mockRejectedValue({ userMessage: 'Unable to load requests.' })
    render(<AdminAIPage api={api} requestsPage onNavigate={vi.fn()} />)
    expect(await screen.findByText('Administrator access required.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve', exact: true })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Tenant AI credit summary')).not.toBeInTheDocument()
  })

  it('does not offer another checkout when a network failure leaves creation uncertain', async () => {
    const api = makeAPI()
    api.startAICreditPurchase.mockRejectedValue({ userMessage: 'Network unavailable.' })
    render(<AdminAIPage api={api} purchasesPage onNavigate={vi.fn()} />)
    await screen.findByText('100')
    fireEvent.click(screen.getByRole('button', { name: 'Purchase Credits' }))
    fireEvent.change(screen.getByLabelText('Credits to purchase'), { target: { value: '50' } })
    fireEvent.click(screen.getByRole('button', { name: 'Get purchase quote' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create checkout' }))
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('check the purchase list')
    expect(screen.queryByRole('button', { name: 'Create checkout' })).not.toBeInTheDocument()
    expect(api.startAICreditPurchase).toHaveBeenCalledTimes(1)
  })

  it('ignores a late snapshot from a previous API or account', async () => {
    const first = makeAPI()
    let resolveFirst
    first.getAIQuotaSummary.mockReturnValue(new Promise((resolve) => { resolveFirst = resolve }))
    const second = makeAPI()
    second.getAIQuotaSummary.mockResolvedValue({ tenant_reserve_credits: 200 })
    const { result, rerender } = renderHook(({ api }) => useAdminAIData(api, 'pending', 0, 0), { initialProps: { api: first } })
    await waitFor(() => expect(first.getAIQuotaSummary).toHaveBeenCalled())
    rerender({ api: second })
    await waitFor(() => expect(result.current.summary?.tenant_reserve_credits).toBe(200))
    await act(async () => { resolveFirst({ tenant_reserve_credits: 100 }) })
    expect(result.current.summary.tenant_reserve_credits).toBe(200)
  })

  it('opens purchases immediately and keeps history as a separate destination', async () => {
    const api = makeAPI()
    const onNavigate = vi.fn()
    render(<AdminAIPage api={api} onNavigate={onNavigate} />)
    await screen.findByRole('button', { name: 'Allocate credits to Ada' })
    fireEvent.click(screen.getByRole('button', { name: 'Purchase Credits' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByLabelText('Credits to purchase')).toBeInTheDocument()
    expect(onNavigate).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByRole('button', { name: 'Purchase history' }))
    expect(onNavigate).toHaveBeenCalledWith('ai-credit-purchases')
    expect(screen.queryByRole('heading', { name: 'Payment history' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.listAICreditPurchases).not.toHaveBeenCalled()
  })

  it('opens payment history when checkout is launched from usage', async () => {
    const api = makeAPI()
    const onNavigate = vi.fn()
    render(<AdminAIPage api={api} onNavigate={onNavigate} />)
    await screen.findByRole('button', { name: 'Allocate credits to Ada' })
    fireEvent.click(screen.getByRole('button', { name: 'Purchase Credits' }))
    fireEvent.change(screen.getByLabelText('Credits to purchase'), { target: { value: '50' } })
    fireEvent.click(screen.getByRole('button', { name: 'Get purchase quote' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create checkout' }))
    fireEvent.click(await screen.findByRole('link', { name: 'Open secure checkout' }))
    expect(onNavigate).toHaveBeenCalledWith('ai-credit-purchases')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('searches names and emails, filters roles, and allocates to the selected staff account', async () => {
    const api = makeAPI()
    api.listAIActorBalances.mockResolvedValue({ items: [
      { quota_account_id: 'quota-1', actor_id: 'actor-1', actor_type: 'teacher', display_name: 'Ada', email: 'ada@school.test', weekly_used_credits: 7, weekly_available_credits: 3, extra_available_credits: 8, total_available_credits: 11 },
      { quota_account_id: 'quota-2', actor_id: 'admin-2', actor_type: 'tenant_admin', display_name: 'Taiwo', email: 'taiwo@school.test', weekly_used_credits: 2, weekly_available_credits: 8, extra_available_credits: 12, total_available_credits: 20 },
    ], total: 2 })
    render(<AdminAIPage api={api} onNavigate={vi.fn()} />)
    const search = await screen.findByRole('searchbox', { name: 'Search staff' })
    fireEvent.change(search, { target: { value: ' TAIWO@school ' } })
    expect(screen.queryByRole('article', { name: 'Ada credits' })).not.toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Taiwo credits' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Allocate credits to Taiwo' }))
    fireEvent.change(screen.getByLabelText('Credits to allocate'), { target: { value: '4' } })
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Allocate credits' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(api.allocateAICredits).toHaveBeenCalledWith({ recipient_actor_id: 'admin-2', recipient_actor_type: 'tenant_admin', credits: 4 })
    expect(screen.getByRole('searchbox')).toHaveValue(' TAIWO@school ')
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'does not exist' } })
    expect(screen.getByText('No matching staff')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getAllByRole('article')).toHaveLength(2)
    fireEvent.click(screen.getByRole('combobox', { name: 'Staff role' }))
    fireEvent.click(screen.getByRole('option', { name: 'Teachers' }))
    expect(screen.getByRole('article', { name: 'Ada credits' })).toBeInTheDocument()
    expect(screen.queryByRole('article', { name: 'Taiwo credits' })).not.toBeInTheDocument()
  })
})
