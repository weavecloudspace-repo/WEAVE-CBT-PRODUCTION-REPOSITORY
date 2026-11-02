import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TeacherAIUsagePage } from '../src/features/teacher/TeacherAIUsagePage'
import { parseStaffPath, pathForStaffState, staffSectionForRole } from '../src/app/staffNavigation'

afterEach(cleanup)

function makeAPI({ exhausted = false, purchases = [] } = {}) {
  const quota = {
    actor_type: 'teacher',
    total_available_credits: exhausted ? 0 : 110,
    weekly: { used_credits: exhausted ? 100 : 10, credit_limit: 100, available_credits: exhausted ? 0 : 90, reserved_credits: 0 },
    extra: { available_credits: exhausted ? 0 : 20, reserved_credits: 0 },
  }
  return {
    getMyAIQuota: vi.fn().mockResolvedValue(quota),
    listMyAIQuotaRequests: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    listTeacherAICreditPurchases: vi.fn().mockResolvedValue({ items: purchases, total: purchases.length }),
    quoteTeacherAICredits: vi.fn().mockResolvedValue({ credits: 20, amount_kobo: 4000, unit_price_kobo: 200, currency: 'NGN' }),
    checkoutTeacherAICredits: vi.fn().mockResolvedValue({ authorization_url: 'https://checkout.example/abc', purchase: { reference: 'teach-ref-1' } }),
    verifyTeacherAICreditPurchase: vi.fn().mockResolvedValue({ status: 'success' }),
    requestAICredits: vi.fn().mockResolvedValue({ id: 'req-1', requested_credits: 20, status: 'pending' }),
  }
}

describe('Teacher AI Usage page', () => {
  it('exposes a teacher-only AI route while keeping admin allocation routes closed', () => {
    expect(staffSectionForRole('teacher', 'ai-usage')).toBe('ai-usage')
    expect(parseStaffPath('/teacher/ai-usage').staffSection).toBe('ai-usage')
    expect(pathForStaffState({ session: { role: 'teacher' }, staff: { section: 'ai-usage' } })).toBe('/teacher/ai-usage')
    expect(staffSectionForRole('teacher', 'ai-credit-requests')).toBe('overview')
    expect(staffSectionForRole('teacher', 'ai-credit-purchases')).toBe('overview')
  })

  it('shows the authenticated teacher balance and weekly consumption without admin data', async () => {
    const api = makeAPI()
    render(<TeacherAIUsagePage api={api} />)
    const region = await screen.findByRole('region', { name: 'Teacher AI credit summary' })
    expect(within(region).getByText('110')).toBeInTheDocument()
    expect(within(region).getByText('10')).toBeInTheDocument()
    expect(within(region).getByText('90')).toBeInTheDocument()
    expect(within(region).getByText('20')).toBeInTheDocument()
    expect(api.getMyAIQuota).toHaveBeenCalledOnce()
    expect(api.quoteTeacherAICredits).not.toHaveBeenCalled()
    expect(screen.queryByText('School credit balance')).not.toBeInTheDocument()
  })

  it('requests a quote, then initiates a teacher-scoped checkout and displays a secure payment link', async () => {
    const api = makeAPI()
    render(<TeacherAIUsagePage api={api} />)
    fireEvent.click(screen.getByRole('button', { name: 'Buy credits' }))
    const dialog = screen.getByRole('dialog', { name: 'Buy personal AI credits' })
    fireEvent.change(within(dialog).getByLabelText('Credits to purchase'), { target: { value: '20' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Get quote' }))
    await waitFor(() => expect(api.quoteTeacherAICredits).toHaveBeenCalledWith(20))
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Create checkout' }))
    await waitFor(() => expect(api.checkoutTeacherAICredits).toHaveBeenCalledWith(20))
    expect(within(dialog).getByRole('link', { name: 'Open secure checkout' })).toHaveAttribute('href', 'https://checkout.example/abc')
    expect(within(dialog).getByText(/teach-ref-1/)).toBeInTheDocument()
  })

  it('rejects invalid credit quantities locally without attempting payment', async () => {
    const api = makeAPI()
    render(<TeacherAIUsagePage api={api} />)
    fireEvent.click(screen.getByRole('button', { name: 'Buy credits' }))
    const dialog = screen.getByRole('dialog', { name: 'Buy personal AI credits' })
    const input = within(dialog).getByLabelText('Credits to purchase')
    for (const bad of ['0', '-2', '1.5']) {
      fireEvent.change(input, { target: { value: bad } })
      expect(within(dialog).getByRole('button', { name: 'Get quote' })).toBeDisabled()
    }
    expect(api.quoteTeacherAICredits).not.toHaveBeenCalled()
  })

  it('shows teacher payment history without school purchases and permits status verification', async () => {
    const item = { id: 'own-1', reference: 'OWN-123', credits: 12, amount_kobo: 2400, currency: 'NGN', status: 'pending', created_at: '2026-10-02T08:00:00Z' }
    const api = makeAPI({ purchases: [item] })
    render(<TeacherAIUsagePage api={api} />)
    fireEvent.click(screen.getByRole('button', { name: 'Purchase history' }))
    expect(await screen.findByText('OWN-123')).toBeInTheDocument()
    expect(api.listTeacherAICreditPurchases).toHaveBeenCalledWith({ offset: 0, limit: 20 })
  })

  it('allows credit requests only for exhausted teacher balances', async () => {
    const api = makeAPI({ exhausted: true })
    render(<TeacherAIUsagePage api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Request credits' }))
    await waitFor(() => expect(api.requestAICredits).toHaveBeenCalledWith(20))
  })
})
