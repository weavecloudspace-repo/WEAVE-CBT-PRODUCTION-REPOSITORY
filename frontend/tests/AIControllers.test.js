import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  approveAIQuotaRequest,
  listAICreditPurchases,
  requestAICredits,
  startAICreditPurchase,
} from '../src/api/ai'
import { clearStaffAccessToken, setStaffAccessToken } from '../src/api/client'

function jsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    text: vi.fn().mockResolvedValue(JSON.stringify(payload)),
  }
}

afterEach(() => {
  clearStaffAccessToken()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('AI management controllers', () => {
  it('requests credits through the protected local CBT API', async () => {
    setStaffAccessToken('local-cbt-jwt')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'request-1' }))
    vi.stubGlobal('fetch', fetchMock)

    await requestAICredits(250)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/ai/quota/requests')
    expect(options.method).toBe('POST')
    expect(options.credentials).toBe('include')
    expect(options.headers.Authorization).toBe('Bearer local-cbt-jwt')
    expect(JSON.parse(options.body)).toEqual({ credits: 250 })
    expect(options.headers['X-CBT-Actor-Authorization']).toBeUndefined()
  })

  it('forwards admin approval payload without exposing cloud credentials', async () => {
    setStaffAccessToken('local-cbt-jwt')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'request-1' }))
    vi.stubGlobal('fetch', fetchMock)

    await approveAIQuotaRequest('request-1', {
      approved_credits: 200,
      note: 'Approved for revision week',
    })

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/ai/admin/quota/requests/request-1/approve')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({
      approved_credits: 200,
      note: 'Approved for revision week',
    })
    expect(options.body).not.toContain('server_credential')
    expect(options.body).not.toContain('actor_access_token')
  })

  it('builds purchase list filters through the local API', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    await listAICreditPurchases({ status: 'success', offset: 10, limit: 25 })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/ai/admin/quota/purchases?status=success&offset=10&limit=25',
    )
  })

  it('starts checkout locally and leaves Paystack ownership with Weave', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ authorization_url: 'https://checkout.example/session' }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await startAICreditPurchase(1000)

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/ai/admin/quota/purchases/checkout')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({ credits: 1000 })
    expect(result.authorization_url).toBe('https://checkout.example/session')
  })
})
