import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import StudentApp from '../src/app/StudentApp'
import { getCurrentAttemptResult } from '../src/api/studentAttempts'
import { studentGateway } from '../src/app/studentGateway'

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

it('exposes the completed result endpoint in the student gateway', () => {
  expect(studentGateway.attempts.getCurrentAttemptResult).toBe(getCurrentAttemptResult)
})

it('sends a returning submitted candidate straight to the score page even if the exam is suspended', async () => {
  window.history.replaceState({}, '', '/student')
  window.localStorage.setItem(
    'weave.cbt.navigation',
    JSON.stringify({ sessionType: 'student', examStage: 'lobby' }),
  )

  const reply = (body) => Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))

  const fetchMock = vi.fn((url) => {
    const path = new URL(url, 'http://localhost').pathname
    if (path.endsWith('/installation/status')) {
      return reply({ configured: true, tenant_name: 'School', server_name: 'Hall 1' })
    }
    if (path.endsWith('/branding')) {
      return reply({ school_name: 'School', is_enabled: false })
    }
    if (path.endsWith('/student/auth/status')) {
      return reply({
        availability: 'completed',
        display_name: 'Ada Okafor',
        student_id: 'student-1',
        candidate_id: 'candidate-1',
        exam_id: 'exam-1',
        exam_title: 'JSS1 English Exam',
        status_message: 'You have already completed this examination. Your score is ready to view.',
        is_makeup: false,
      })
    }
    if (path.endsWith('/student/attempts/current/result')) {
      return reply({
        attempt_id: 'attempt-1',
        subject_name: 'Literature',
        status: 'submitted',
        end_reason: 'candidate_submitted',
        ended_at: '2026-09-28T18:30:00Z',
        result_id: 'result-1',
        raw_score: 8,
        raw_max_score: 10,
        percentage: '80.00',
        component_score: '16.00',
        component_maximum_score: '20.00',
      })
    }
    return Promise.reject(new Error(`Unexpected request ${path}`))
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<BrowserRouter><StudentApp /></BrowserRouter>)

  expect(await screen.findByRole('heading', { name: /exam submitted/i })).toBeInTheDocument()
  expect(screen.getByText('Literature')).toBeInTheDocument()
  expect(screen.getByLabelText(/score 8 \/ 10, 80.00 percent/i)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /start exam/i })).not.toBeInTheDocument()
  expect(screen.queryByText(/exam suspended/i)).not.toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: /exam currently suspended/i })).not.toBeInTheDocument()

  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).endsWith('/student/attempts/current/result')),
    ).toBe(true)
  })
})
