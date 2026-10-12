import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'

import App from '../src/App'

const bankId = '99999999-9999-9999-9999-999999999999'
const questionId = '12121212-1212-1212-1212-121212121212'

const pairedStatus = {
  configured: true,
  server_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  server_name: 'Brightfield CBT Lab',
  tenant_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
  tenant_name: 'Brightfield Academy',
  paired_at: '2026-08-22T09:00:00Z',
}

const teacherLogin = {
  access_token: 'staff-token',
  token_type: 'bearer',
  actor: {
    id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
    role: 'teacher',
    email: 'teacher@brightfield.test',
    display_name: 'Mrs. Amina Khan',
  },
}

const bank = {
  id: bankId,
  curriculum_subject_id: 'abababab-abab-abab-abab-abababababab',
  name: 'Backend Biology Bank',
  description: 'Loaded from API',
  created_by_actor_id: teacherLogin.actor.id,
  is_active: true,
}

const question = {
  id: questionId,
  bank_id: bankId,
  question_type: 'single_choice',
  prompt: 'Which cell structure releases energy?',
  instruction: null,
  image_asset_id: null,
  version: 1,
  created_by_actor_id: teacherLogin.actor.id,
  last_edited_by_actor_id: null,
  is_active: true,
  options: [
    { id: 'option-1', text: 'Mitochondrion', is_correct: true },
    { id: 'option-2', text: 'Nucleus', is_correct: false },
  ],
}

function jsonResponse(body, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

function installFetch() {
  vi.stubGlobal('fetch', vi.fn((url, options = {}) => {
    const parsed = new URL(url, 'http://localhost')
    const method = options.method || 'GET'
    const key = `${method} ${parsed.pathname}`

    const routes = {
      'GET /api/v1/installation/status': () => jsonResponse(pairedStatus),
      'POST /api/v1/auth/login': () => jsonResponse(teacherLogin),
      'GET /api/v1/questions/manageable': () => jsonResponse([question]),
      'GET /api/v1/questions/banks/authorable': () => jsonResponse([bank]),
      [`GET /api/v1/questions/banks/${bankId}/items`]: () => jsonResponse([question]),
      [`GET /api/v1/questions/${questionId}`]: () => jsonResponse(question),
    }

    return routes[key]?.() || jsonResponse({ detail: `Unhandled ${key}` }, 500)
  }))
}

describe('teacher question edit routing', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
    window.localStorage.clear()
    vi.restoreAllMocks()
    installFetch()
  })

  it('keeps edit-question as a valid teacher route and opens the editor', async () => {
    render(<BrowserRouter><App /></BrowserRouter>)

    const staffLoginButton = await screen.findByRole('button', { name: /login as staff/i })
    fireEvent.click(staffLoginButton)
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'teacher@brightfield.test' } })
    fireEvent.change(screen.getByPlaceholderText(/enter your password/i), { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    const sidebar = await screen.findByRole('navigation', { name: /teacher navigation/i })
    fireEvent.click(within(sidebar).getByRole('button', { name: /^questions$/i }))

    expect(await screen.findByText(question.prompt)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))

    await waitFor(() => expect(window.location.pathname).toBe(`/teacher/questions/${questionId}/edit`))
    expect(await screen.findByRole('heading', { name: 'Question content' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Question prompt')).toHaveValue(question.prompt))
  })
})
