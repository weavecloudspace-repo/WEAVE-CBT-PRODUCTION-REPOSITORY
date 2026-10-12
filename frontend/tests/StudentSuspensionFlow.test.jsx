import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import StudentApp from '../src/app/StudentApp'
import { studentGateway } from '../src/app/studentGateway'
import { heartbeatCurrentAttempt } from '../src/api/studentAttempts'

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

it('exposes the real heartbeat endpoint in the student gateway', () => {
  expect(studentGateway.attempts.heartbeatCurrentAttempt).toBe(heartbeatCurrentAttempt)
})

it('returns a suspended student to the waiting room without logging them out', async () => {
  window.history.replaceState({}, '', '/student/exam')
  window.localStorage.setItem(
    'weave.cbt.navigation',
    JSON.stringify({ sessionType: 'student', examStage: 'active' }),
  )
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }
  const reply = (body) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  let statusRequests = 0
  const fetchMock = vi.fn((url, options = {}) => {
    const path = new URL(url, 'http://localhost').pathname
    if (path.endsWith('/installation/status')) return reply({ configured: true, tenant_name: 'School', server_name: 'Hall 1' })
    if (path.endsWith('/branding')) return reply({ school_name: 'School', is_enabled: false })
    if (path.endsWith('/student/auth/status')) {
      statusRequests += 1
      return reply({
        availability: statusRequests === 1 ? 'ready' : 'suspended',
        display_name: 'Ada',
        student_id: 'student',
        candidate_id: 'candidate',
        exam_id: 'exam',
        exam_title: 'English',
        status_message: statusRequests === 1
          ? 'Your examination is ready to begin.'
          : 'The school has paused this examination.',
        is_makeup: false,
      })
    }
    if (path.endsWith('/student/attempts/current') && (!options.method || options.method === 'GET')) {
      return reply({
        id: 'attempt',
        exam_id: 'exam',
        exam_title: 'English',
        status: 'in_progress',
        remaining_seconds: 1200,
        exam_suspended: true,
        questions: [],
      })
    }
    if (path.endsWith('/student/auth/logout') && options.method === 'POST') return reply({})
    return Promise.reject(new Error(`Unexpected request ${path}`))
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<BrowserRouter><StudentApp /></BrowserRouter>)

  const modal = await screen.findByRole('dialog', { name: 'Exam currently suspended' })
  await waitFor(() => expect(window.location.pathname).toBe('/student'))
  expect(modal).toHaveTextContent('Your session is still active')
  expect(
    fetchMock.mock.calls.some(
      ([url, options]) => String(url).endsWith('/student/auth/logout') && options.method === 'POST',
    ),
  ).toBe(false)

  fireEvent.click(screen.getByRole('button', { name: 'Understood' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(screen.getByRole('button', { name: 'Waiting for exam to resume...' })).toBeDisabled()
  expect(window.location.pathname).toBe('/student')
})