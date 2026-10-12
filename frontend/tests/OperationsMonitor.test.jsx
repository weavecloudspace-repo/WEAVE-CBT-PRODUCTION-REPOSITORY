import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadAttemptSnapshot, useOperationsMonitor } from '../src/features/admin/useOperationsMonitor'

afterEach(() => vi.useRealTimers())

describe('Operations monitoring snapshots', () => {
  it('collects all pages rather than treating the first page as the total', async () => {
    const list = vi.fn()
      .mockResolvedValueOnce({ total: 201, attempts: Array.from({ length: 200 }, (_, id) => ({ id: String(id) })) })
      .mockResolvedValueOnce({ total: 201, attempts: [{ id: '200' }] })
    const signal = new AbortController().signal
    const rows = await loadAttemptSnapshot(list, 'exam', signal)
    expect(rows).toHaveLength(201)
    expect(list).toHaveBeenLastCalledWith('exam', { offset: 200, limit: 200 }, { signal })
  })

  it('rejects an incomplete response instead of publishing misleading totals', async () => {
    const list = vi.fn().mockResolvedValue({ total: 5, attempts: [] })
    await expect(loadAttemptSnapshot(list, 'exam', new AbortController().signal)).rejects.toThrow('Incomplete monitoring response')
  })

  it('aborts the old sitting request when selection changes and ignores late responses', async () => {
    let resolveOld
    const list = vi.fn((id) => id === 'old'
      ? new Promise((resolve) => { resolveOld = resolve })
      : Promise.resolve({ total: 1, attempts: [{ id: 'new-attempt' }] }))
    const { result, rerender } = renderHook(({ id }) => useOperationsMonitor(id, list), { initialProps: { id: 'old' } })
    const oldSignal = list.mock.calls[0][2].signal
    rerender({ id: 'new' })
    expect(oldSignal.aborted).toBe(true)
    await waitFor(() => expect(result.current.attempts).toEqual([{ id: 'new-attempt' }]))
    await act(async () => resolveOld({ total: 1, attempts: [{ id: 'old-attempt' }] }))
    expect(result.current.attempts).toEqual([{ id: 'new-attempt' }])
  })

  it('retains last known data with an explicit error after refresh failure', async () => {
    vi.useFakeTimers()
    const list = vi.fn().mockResolvedValueOnce({ total: 1, attempts: [{ id: 'attempt' }] }).mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useOperationsMonitor('exam', list))
    await act(async () => {})
    expect(result.current.attempts).toHaveLength(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(result.current.attempts).toHaveLength(1)
    expect(result.current.error).toMatch(/could not refresh/)
  })
})
