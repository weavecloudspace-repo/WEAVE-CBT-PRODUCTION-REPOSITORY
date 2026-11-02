import { describe, expect, it } from 'vitest'
import * as ai from '../src/api/ai'
import { vi } from 'vitest'

vi.mock('../src/api/client', () => ({
  weaveRequest: vi.fn(async (path, options) => ({ path, options })),
  queryString: (params) => '?' + new URLSearchParams(params).toString(),
}))

describe('teacher purchase API contracts', () => {
  it('routes personal purchases separately from admin school-reserve purchases', async () => {
    expect((await ai.quoteTeacherAICredits(20)).path).toBe('/ai/teacher/purchases/quote')
    expect((await ai.checkoutTeacherAICredits(20)).options.body).toEqual({ credits: 20 })
    expect((await ai.listTeacherAICreditPurchases({ offset: 0, limit: 20 })).path).toBe('/ai/teacher/purchases?offset=0&limit=20')
    const result = await ai.verifyTeacherAICreditPurchase('ref/a')
    expect(result.path).toBe('/ai/teacher/purchases/ref%2Fa/verify')
    expect(result.options.method).toBe('POST')
  })
})
