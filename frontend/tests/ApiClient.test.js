import { afterEach, describe, expect, it, vi } from 'vitest'
import { weaveRequest } from '../src/api/client'

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('API error messages', () => {
  it('shows the structured backend message for an expired exam schedule', async () => {
    const message = 'This examination was scheduled for a previous date. Reschedule it before activation.'
    const payload = {
      detail: {
        code: 'activation_schedule_date_expired',
        message,
        preflight: {
          blockers: ['schedule_date_expired'],
        },
      },
    }

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      text: vi.fn().mockResolvedValue(JSON.stringify(payload)),
    }))

    try {
      await weaveRequest('/exams/example/activate', { method: 'POST' })
      throw new Error('Expected weaveRequest to reject')
    } catch (error) {
      expect(error.userMessage).toBe(message)
      expect(error.payload).toEqual(payload)
    }
  })

  it('uses a plain-language fallback for an otherwise empty conflict response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      text: vi.fn().mockResolvedValue(''),
    }))

    try {
      await weaveRequest('/exams/example/activate', { method: 'POST' })
      throw new Error('Expected weaveRequest to reject')
    } catch (error) {
      expect(error.userMessage).toBe('This action is not available right now')
    }
  })
})
