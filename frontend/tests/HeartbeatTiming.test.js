import { describe, expect, it, vi } from 'vitest'
import { initialHeartbeatDelayMs, jitteredHeartbeatDelayMs, singleFlight } from '../src/features/student/heartbeatTiming'

describe('client-only exam heartbeat scheduling', () => {
  it('spreads the first heartbeat across 20 seconds', () => {
    expect(initialHeartbeatDelayMs(() => 0)).toBe(0)
    expect(initialHeartbeatDelayMs(() => 0.5)).toBe(10_000)
    expect(initialHeartbeatDelayMs(() => 0.999)).toBe(19_980)
  })

  it('keeps the recommended 20-second interval with two-second jitter', () => {
    expect(jitteredHeartbeatDelayMs(20_000, () => 0)).toBe(18_000)
    expect(jitteredHeartbeatDelayMs(20_000, () => 0.5)).toBe(20_000)
    expect(jitteredHeartbeatDelayMs(20_000, () => 1)).toBe(22_000)
  })

  it('jitters retry scheduling without allowing excessively short delays', () => {
    expect(jitteredHeartbeatDelayMs(10_000, () => 0)).toBe(8_000)
    expect(jitteredHeartbeatDelayMs(10_000, () => 1)).toBe(12_000)
    expect(jitteredHeartbeatDelayMs(5_000, () => 0)).toBe(5_000)
  })

  it('suppresses overlapping requests and allows a later heartbeat', async () => {
    let resolveFirst
    const operation = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce('second')
    const run = singleFlight(operation)

    const first = run()
    expect(await run()).toBeUndefined()
    expect(operation).toHaveBeenCalledOnce()
    resolveFirst('first')
    expect(await first).toBe('first')
    expect(await run()).toBe('second')
    expect(operation).toHaveBeenCalledTimes(2)
  })

  it('releases the in-flight guard after request failure', async () => {
    const operation = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce('online')
    const run = singleFlight(operation)
    await expect(run()).rejects.toThrow('offline')
    await expect(run()).resolves.toBe('online')
    expect(operation).toHaveBeenCalledTimes(2)
  })
})
