import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'

import App from '../src/App'

const examId = '11111111-1111-1111-1111-111111111111'
const candidateId = '22222222-2222-2222-2222-222222222222'
const attemptQuestionId = '44444444-4444-4444-4444-444444444444'
const optionId = '55555555-5555-5555-5555-555555555555'
const bankId = '99999999-9999-9999-9999-999999999999'

function renderApp() {
  render(<BrowserRouter><App /></BrowserRouter>)
}

function jsonResponse(body, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

function installFetch(routes = {}) {
  const fetchMock = vi.fn((url, options = {}) => {
    const parsed = new URL(url, 'http://localhost')
    const method = options.method || 'GET'
    const key = `${method} ${parsed.pathname}`
    const route = routes[key]
    if (route) return route({ url: parsed, options })
    return jsonResponse({ detail: `Unhandled ${key}` }, 500)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const pairedStatus = {
  configured: true,
  server_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  server_name: 'Brightfield CBT Lab',
  tenant_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
  tenant_name: 'Brightfield Academy',
  paired_at: '2026-08-22T09:00:00Z',
}

const staffLogin = (role = 'teacher') => ({
  access_token: 'staff-token',
  token_type: 'bearer',
  actor: {
    id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
    role,
    email: `${role}@brightfield.test`,
    display_name: role === 'admin' ? 'Amina Yusuf' : 'Mrs. Amina Khan',
  },
})

const teacherBank = {
  id: bankId,
  curriculum_subject_id: 'abababab-abab-abab-abab-abababababab',
  name: 'Backend Biology Bank',
  description: 'Loaded from API',
  created_by_actor_id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
  is_active: true,
}

const teacherQuestion = {
  id: '12121212-1212-1212-1212-121212121212',
  bank_id: bankId,
  question_type: 'single_choice',
  prompt: 'Which cell structure releases energy?',
  instruction: null,
  image_asset_id: null,
  version: 1,
  created_by_actor_id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
  last_edited_by_actor_id: null,
  is_active: true,
  options: [],
}

describe('Weave backend integration shell', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it('boots from installation status and opens the real login flow', async () => {
    installFetch({
      'GET /api/v1/installation/status': () => jsonResponse(pairedStatus),
    })

    renderApp()

    expect(screen.getByRole('heading', { name: /starting weave/i })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /login as staff/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /login as student/i })).toBeInTheDocument()
    expect(screen.queryByLabelText(/temporary role switcher/i)).not.toBeInTheDocument()
  })

  it('shows pairing before login when the backend reports an unpaired node', async () => {
    const fetchMock = installFetch({
      'GET /api/v1/installation/status': () => jsonResponse({ configured: false }),
      'POST /api/v1/installation/pair': ({ options }) => {
        expect(JSON.parse(options.body)).toMatchObject({
          pairing_code: 'WEAVE2026',
          server_name: 'Brightfield CBT Lab',
        })
        return jsonResponse(pairedStatus)
      },
    })

    renderApp()

    expect(await screen.findByRole('heading', { name: /welcome to/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /get started/i }))
    fireEvent.change(screen.getByLabelText(/pairing code/i), { target: { value: 'weave2026' } })
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: 'Brightfield CBT Lab' } })
    fireEvent.click(screen.getByRole('button', { name: /complete setup/i }))

    expect(await screen.findByRole('heading', { name: /successfully paired/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /continue to home/i }))
    expect(await screen.findByRole('button', { name: /login as staff/i })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/installation/pair', expect.objectContaining({ method: 'POST' }))
  })

  it('uses staff auth and renders teacher-only navigation', async () => {
    const fetchMock = installFetch({
      'GET /api/v1/installation/status': () => jsonResponse(pairedStatus),
      'POST /api/v1/auth/login': () => jsonResponse(staffLogin('teacher')),
      'GET /api/v1/questions/banks/authorable': () => jsonResponse([teacherBank]),
      [`GET /api/v1/questions/banks/${bankId}/items`]: () => jsonResponse([teacherQuestion]),
    })

    renderApp()

    const staffLoginButton = await screen.findByRole('button', { name: /login as staff/i })
    fireEvent.click(staffLoginButton)
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'teacher@brightfield.test' } })
    fireEvent.change(screen.getByPlaceholderText(/enter your password/i), { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    const sidebar = await screen.findByRole('navigation', { name: /teacher navigation/i })
    const banksButton = within(sidebar).getByRole('button', { name: /question banks/i })
    expect(banksButton).toBeInTheDocument()
    expect(within(sidebar).queryByRole('button', { name: /rosters/i })).not.toBeInTheDocument()
    fireEvent.click(banksButton)
    expect(await screen.findByText(/backend biology bank/i)).toBeInTheDocument()
    expect(screen.queryByText(/biology ca1 bank/i)).not.toBeInTheDocument()
    expect(window.localStorage.getItem('weave.staffAccessToken')).toBe('staff-token')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/questions/banks/authorable', expect.anything())
    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/questions/banks/${bankId}/items?include_archived=true`, expect.anything())
  })

  it('routes an admin into the workspace after a completed backend bootstrap', async () => {
    const fetchMock = installFetch({
      'GET /api/v1/installation/status': () => jsonResponse(pairedStatus),
      'POST /api/v1/auth/login': () => jsonResponse(staffLogin('admin')),
      'GET /api/v1/sync/status': () => jsonResponse({ bootstrap_completed_at: '2026-08-22T09:00:00Z', last_error: null }),
    })

    renderApp()

    await loginAsAdmin()
    expect(screen.getByRole('navigation', { name: /administrator navigation/i })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/sync/status', expect.anything())
  })

  it('uses student auth and saves answers through the current-attempt API', async () => {
    const fetchMock = installFetch({
      'GET /api/v1/installation/status': () => jsonResponse(pairedStatus),
      'POST /api/v1/student/auth/login': ({ options }) => {
        expect(JSON.parse(options.body)).toEqual({
          admission_number: 'BFA/24/001',
          password: 'bfa/24/001',
        })
        return jsonResponse({
          student_id: '77777777-7777-7777-7777-777777777777',
          candidate_id: candidateId,
          exam_id: examId,
          exam_title: 'Mathematics CA1',
          display_name: 'Taiwo Adewale',
          availability: 'ready',
          is_makeup: false,
          scheduled_start_at: null,
          activated_at: '2026-08-22T09:00:00Z',
        })
      },
      'GET /api/v1/student/auth/status': () => jsonResponse({
        student_id: '77777777-7777-7777-7777-777777777777',
        candidate_id: candidateId,
        exam_id: examId,
        exam_title: 'Mathematics CA1',
        display_name: 'Taiwo Adewale',
        availability: 'ready',
        is_makeup: false,
        scheduled_start_at: null,
        activated_at: '2026-08-22T09:00:00Z',
      }),
      'POST /api/v1/student/attempts/current/start': () => jsonResponse(currentAttempt()),
      'GET /api/v1/student/attempts/current': () => jsonResponse(currentAttempt()),
      [`PUT /api/v1/student/attempts/current/questions/${attemptQuestionId}/answer`]: ({ options }) => {
        expect(JSON.parse(options.body)).toMatchObject({ mutation_sequence: 1, selected_option_ids: [optionId] })
        return jsonResponse({
          attempt_id: '88888888-8888-8888-8888-888888888888',
          attempt_question_id: attemptQuestionId,
          mutation_sequence: 1,
          selected_option_ids: [optionId],
          is_flagged: false,
          remaining_seconds: 3590,
        })
      },
    })

    renderApp()

    const studentLoginButton = await screen.findByRole('button', { name: /login as student/i })
    fireEvent.click(studentLoginButton)
    fireEvent.change(screen.getByLabelText(/admission number/i), { target: { value: 'bfa/24/001' } })
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'bfa/24/001' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByRole('heading', { name: /mathematics ca1/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /start exam/i }))
    expect(await screen.findByText(/what is 2 \+ 2/i)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/four/i))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`/api/v1/student/attempts/current/questions/${attemptQuestionId}/answer`, expect.objectContaining({ method: 'PUT' })))
  })
})

async function loginAsAdmin() {
  const staffLoginButton = await screen.findByRole('button', { name: /login as staff/i })
  fireEvent.click(staffLoginButton)
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'admin@brightfield.test' } })
  fireEvent.change(screen.getByPlaceholderText(/enter your password/i), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
  await screen.findByText(/^administrator$/i)
}

function currentAttempt() {
  return {
    id: '88888888-8888-8888-8888-888888888888',
    candidate_id: candidateId,
    exam_id: examId,
    exam_title: 'Mathematics CA1',
    status: 'in_progress',
    started_at: '2026-08-22T09:00:00Z',
    ended_at: null,
    end_reason: null,
    time_limit_seconds: 3600,
    remaining_seconds: 3600,
    is_makeup: false,
    exam_suspended: false,
    questions: [
      {
        id: attemptQuestionId,
        position: 1,
        question_type: 'single_choice',
        prompt: 'What is 2 + 2?',
        instruction: null,
        image_asset_id: null,
        selected_option_ids: [],
        is_flagged: false,
        mutation_sequence: 0,
        options: [{ id: optionId, position: 1, text: 'Four' }],
      },
    ],
  }
}
