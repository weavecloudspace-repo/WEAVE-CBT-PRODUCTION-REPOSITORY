import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearStaffSession,
  refreshStaff,
} from '../src/api/staffAuth'
import { getStaffAccessToken } from '../src/api/client'

const OPERATION_KEY = 'weave.staffRefreshOperationId'
const OPERATION_ID = '11111111-1111-4111-8111-111111111111'

function successfulRefreshResponse() {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    text: vi.fn().mockResolvedValue(JSON.stringify({
      access_token: 'local-access-2',
      access_token_expires_at: '2099-01-01T00:20:00Z',
      session_expires_at: '2099-01-01T12:00:00Z',
      cloud_auth_state: 'synced',
      token_type: 'bearer',
      actor: {
        id: '33333333-3333-4333-8333-333333333333',
        role: 'teacher',
        email: 'teacher@example.com',
        display_name: 'Teacher One',
      },
    })),
  }
}

afterEach(() => {
  clearStaffSession()
  window.localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('staff auth refresh', () => {
  it('sends the shared idempotency key and advances it only after success', async () => {
    window.localStorage.setItem(OPERATION_KEY, OPERATION_ID)
    vi.spyOn(window, 'setTimeout').mockReturnValue(1)

    const fetchMock = vi.fn().mockResolvedValue(successfulRefreshResponse())
    vi.stubGlobal('fetch', fetchMock)

    const session = await refreshStaff()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/auth/refresh')
    expect(fetchMock.mock.calls[0][1].headers['Idempotency-Key']).toBe(OPERATION_ID)
    const nextOperationId = window.localStorage.getItem(OPERATION_KEY)
    expect(nextOperationId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    expect(nextOperationId).not.toBe(OPERATION_ID)
    expect(getStaffAccessToken()).toBe('local-access-2')
    expect(session.accessTokenExpiresAt).toBe('2099-01-01T00:20:00Z')
    expect(session.sessionExpiresAt).toBe('2099-01-01T12:00:00Z')
    expect(session.cloudAuthState).toBe('synced')
  })

  it('keeps the same operation id after a transient failure', async () => {
    window.localStorage.setItem(OPERATION_KEY, OPERATION_ID)

    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      text: vi.fn().mockResolvedValue(JSON.stringify({ detail: 'Retry later.' })),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(refreshStaff()).rejects.toMatchObject({ status: 503 })

    expect(fetchMock.mock.calls[0][1].headers['Idempotency-Key']).toBe(OPERATION_ID)
    expect(window.localStorage.getItem(OPERATION_KEY)).toBe(OPERATION_ID)
  })
})
