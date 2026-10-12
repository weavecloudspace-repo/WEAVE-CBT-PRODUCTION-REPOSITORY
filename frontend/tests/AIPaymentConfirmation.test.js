import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAIPaymentConfirmation } from '../src/features/admin/useAIPaymentConfirmation'

const purchases = { items: [{ reference: 'pending-1', status: 'pending' }, { reference: 'paid-1', status: 'success' }] }
const flush = async () => { await act(async () => { await Promise.resolve() }) }

beforeEach(() => vi.useFakeTimers())
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('Automatic AI payment confirmation', () => {
  it('checks only pending purchases and refreshes server balances after success', async () => {
    const api = { verifyAICreditPurchase: vi.fn().mockResolvedValue({ status: 'success' }) }
    const refresh = vi.fn().mockResolvedValue()
    renderHook(() => useAIPaymentConfirmation(api, purchases, refresh))
    await flush()
    expect(api.verifyAICreditPurchase).toHaveBeenCalledTimes(1)
    expect(api.verifyAICreditPurchase.mock.calls[0][0]).toBe('pending-1')
    expect(refresh).toHaveBeenCalledTimes(1)
    await act(async () => vi.advanceTimersByTimeAsync(60_000))
    expect(api.verifyAICreditPurchase).toHaveBeenCalledTimes(1)
  })

  it('retries incomplete checks and immediately resumes when checkout returns focus', async () => {
    const api = { verifyAICreditPurchase: vi.fn().mockRejectedValue({ status: 400 }) }
    const refresh = vi.fn().mockResolvedValue()
    renderHook(() => useAIPaymentConfirmation(api, purchases, refresh))
    await flush()
    expect(refresh).not.toHaveBeenCalled()
    await act(async () => vi.advanceTimersByTimeAsync(15_000))
    expect(api.verifyAICreditPurchase).toHaveBeenCalledTimes(2)
    api.verifyAICreditPurchase.mockResolvedValue({ status: 'success' })
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(api.verifyAICreditPurchase).toHaveBeenCalledTimes(3)
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('bounds polling and resumes on focus without inventing a successful payment', async () => {
    const api = { verifyAICreditPurchase: vi.fn().mockResolvedValue({ status: 'pending' }) }
    const refresh = vi.fn()
    const { result } = renderHook(() => useAIPaymentConfirmation(api, purchases, refresh))
    await flush()
    await act(async () => vi.advanceTimersByTimeAsync(6 * 60_000))
    expect(result.current).toBe('paused')
    const count = api.verifyAICreditPurchase.mock.calls.length
    await act(async () => vi.advanceTimersByTimeAsync(60_000))
    expect(api.verifyAICreditPurchase).toHaveBeenCalledTimes(count)
    expect(refresh).not.toHaveBeenCalled()
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(api.verifyAICreditPurchase).toHaveBeenCalledTimes(count + 1)
  })

  it('aborts on unmount and ignores late confirmation', async () => {
    let resolve
    const api = { verifyAICreditPurchase: vi.fn(() => new Promise((done) => { resolve = done })) }
    const refresh = vi.fn()
    const { unmount } = renderHook(() => useAIPaymentConfirmation(api, purchases, refresh))
    const signal = api.verifyAICreditPurchase.mock.calls[0][1].signal
    unmount()
    expect(signal.aborted).toBe(true)
    await act(async () => resolve({ status: 'success' }))
    expect(refresh).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })
})
