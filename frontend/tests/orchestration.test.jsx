import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import App from '../src/App'

const paired = { configured: true, tenant_name: 'Brightfield Academy', server_name: 'Main CBT Lab' }
const unpaired = { configured: false }
const branding = { school_name: 'Brightfield Academy', is_enabled: true, logo_revision: 'logo-revision', logo_path: '/api/v1/branding/logo', light_tokens: { '--color-primary': '4 120 87' } }
const admin = { access_token: 'admin-token', actor: { role: 'admin', display_name: 'Amina Yusuf' } }
const teacher = { access_token: 'teacher-token', actor: { role: 'teacher', display_name: 'Mrs. Khan' } }
const incomplete = { bootstrap_completed_at: null, last_error: null }
const complete = { bootstrap_completed_at: '2026-09-15T08:00:00Z', last_error: null }

const reply = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

function routes(overrides = {}) {
  const handlers = {
    'GET /api/v1/installation/status': () => reply(paired),
    'GET /api/v1/branding': () => reply(branding),
    ...overrides,
  }
  const fetchMock = vi.fn((url, options = {}) => {
    const path = new URL(url, 'http://localhost').pathname
    return (handlers[`${options.method || 'GET'} ${path}`] || (() => reply({ detail: 'Unexpected request' }, 500)))(options)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function openSetup() {
  await screen.findByRole('heading', { name: /welcome to/i })
  await waitFor(() => expect(window.location.pathname).toBe('/setup'))
  fireEvent.click(screen.getByRole('button', { name: /get started/i }))
  await screen.findByLabelText(/pairing code/i)
}

function renderApp() {
  render(<BrowserRouter><App /></BrowserRouter>)
}

async function submitCode() {
  await openSetup()
  fireEvent.change(screen.getByLabelText(/pairing code/i), { target: { value: 'CBT12345' } })
  fireEvent.click(screen.getByRole('button', { name: /continue/i }))
  await screen.findByLabelText(/server name/i)
}

async function openStaff() {
  const staffLoginButton = await screen.findByRole('button', { name: /login as staff/i })
  fireEvent.click(staffLoginButton)
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'admin@school.test' } })
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
}

describe('Weave setup and first sync orchestration', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it('uses installation status to show welcome only on an unpaired server', async () => {
    routes({ 'GET /api/v1/installation/status': () => reply(unpaired) })
    renderApp()
    expect(await screen.findByRole('heading', { name: /welcome to/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /login as staff/i })).not.toBeInTheDocument()
  })

  it('keeps an unpaired setup subroute instead of returning to the welcome screen', async () => {
    window.history.pushState({}, '', '/setup/pairing-code')
    routes({ 'GET /api/v1/installation/status': () => reply(unpaired) })
    renderApp()
    expect(await screen.findByRole('heading', { name: /enter pairing code/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /get started/i })).not.toBeInTheDocument()
  })

  it('skips setup on a configured server even after a new render', async () => {
    routes()
    renderApp()
    expect(await screen.findByRole('button', { name: /login as staff/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /login as student/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /get started/i })).not.toBeInTheDocument()
  })

  it('collects a code before any pairing request and then collects the server name', async () => {
    const fetchMock = routes({ 'GET /api/v1/installation/status': () => reply(unpaired) })
    renderApp()
    await submitCode()
    expect(screen.getByRole('heading', { name: /set a server name/i })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/installation/pair')).toBe(false)
  })

  it('requires the backend code length despite the OTP visual treatment', async () => {
    const fetchMock = routes({ 'GET /api/v1/installation/status': () => reply(unpaired) })
    renderApp()
    await openSetup()
    fireEvent.change(screen.getByLabelText(/pairing code/i), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))
    expect(screen.getByText(/8–20 characters/i)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/installation/pair')).toBe(false)
  })

  it('shows real in-flight pairing activity and enters success only after the API resolves', async () => {
    let finish
    const fetchMock = routes({
      'GET /api/v1/installation/status': () => reply(unpaired),
      'POST /api/v1/installation/pair': () => new Promise((resolve) => { finish = resolve }),
    })
    renderApp()
    await submitCode()
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: 'Main CBT Lab' } })
    fireEvent.click(screen.getByRole('button', { name: /complete setup/i }))
    expect(screen.getByRole('heading', { name: /pairing with weave/i })).toBeInTheDocument()
    expect(screen.getByText(/verifying your code and connecting/i)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /successfully paired/i })).not.toBeInTheDocument()
    expect(JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/v1/installation/pair')[1].body)).toEqual({ pairing_code: 'CBT12345', server_name: 'Main CBT Lab' })
    finish(new Response(JSON.stringify(paired), { status: 201 }))
    expect(await screen.findByRole('heading', { name: /successfully paired/i })).toBeInTheDocument()
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === '/api/v1/branding').length).toBeGreaterThan(1))
  })

  it('keeps values and offers retry after pairing fails', async () => {
    routes({ 'GET /api/v1/installation/status': () => reply(unpaired), 'POST /api/v1/installation/pair': () => reply({ detail: 'Invalid pairing code' }, 400) })
    renderApp()
    await submitCode()
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: 'Main CBT Lab' } })
    fireEvent.click(screen.getByRole('button', { name: /complete setup/i }))
    expect(await screen.findByRole('button', { name: /retry pairing/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /edit server name/i }))
    expect(screen.getByLabelText(/server name/i)).toHaveValue('Main CBT Lab')
  })

  it('rechecks backend status on an already-paired conflict', async () => {
    let statusReads = 0
    const fetchMock = routes({
      'GET /api/v1/installation/status': () => reply(++statusReads === 1 ? unpaired : paired),
      'POST /api/v1/installation/pair': () => reply({ detail: 'Already paired' }, 409),
    })
    renderApp()
    await submitCode()
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: 'Main CBT Lab' } })
    fireEvent.click(screen.getByRole('button', { name: /complete setup/i }))
    expect(await screen.findByRole('heading', { name: /successfully paired/i })).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/v1/installation/status')).toHaveLength(2)
  })

  it('continues with default Weave blue when branding fails', async () => {
    routes({ 'GET /api/v1/branding': () => reply({ detail: 'Unavailable' }, 503) })
    const { container } = render(<BrowserRouter><App /></BrowserRouter>)
    expect(await screen.findByRole('button', { name: /login as staff/i })).toBeInTheDocument()
    expect(container.firstChild.style.getPropertyValue('--color-primary')).toBe('29 78 216')
  })

  it('applies local school branding and uses the local logo endpoint', async () => {
    routes()
    const { container } = render(<BrowserRouter><App /></BrowserRouter>)
    await screen.findByRole('button', { name: /login as staff/i })
    await waitFor(() => expect(container.firstChild.style.getPropertyValue('--color-primary')).toBe('4 120 87'))
    fireEvent.click(screen.getByRole('button', { name: /login as staff/i }))
    expect(container.querySelector('.weave-login-tenant-logo')).toHaveAttribute('src', '/api/v1/branding/logo?v=logo-revision')
  })

  it('routes landing actions to separate staff and student pages with no role selector', async () => {
    routes()
    renderApp()
    const studentLoginButton = await screen.findByRole('button', { name: /login as student/i })
    fireEvent.click(studentLoginButton)
    expect(screen.getByRole('heading', { name: /student login/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/admission number/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /back to home/i }))
    fireEvent.click(screen.getByRole('button', { name: /login as staff/i }))
    expect(screen.getByRole('heading', { name: /staff login/i })).toBeInTheDocument()
    expect(screen.queryByText(/admin or teacher/i)).not.toBeInTheDocument()
  })

  it('opens each login form with a clean credential and error context', async () => {
    routes({ 'POST /api/v1/student/auth/login': () => reply({ detail: 'Invalid student credential' }, 401) })
    renderApp()
    await screen.findByRole('button', { name: /login as student/i })

    fireEvent.click(screen.getByRole('button', { name: /login as student/i }))
    fireEvent.change(screen.getByLabelText(/admission number/i), { target: { value: 'BFA/24/001' } })
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'student-secret' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(await screen.findByText(/invalid student credential/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /back to home/i }))
    fireEvent.click(screen.getByRole('button', { name: /login as staff/i }))

    expect(screen.queryByText(/invalid student credential/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/email/i)).toHaveValue('')
    expect(screen.getByLabelText(/^password$/i)).toHaveValue('')
    expect(screen.getByLabelText(/email/i)).toHaveAttribute('autocomplete', 'off')
    expect(screen.getByLabelText(/^password$/i)).toHaveAttribute('autocomplete', 'new-password')
  })

  it('checks backend sync status only after admin sign in', async () => {
    const fetchMock = routes({ 'POST /api/v1/auth/login': () => reply(admin), 'GET /api/v1/sync/status': () => reply(incomplete) })
    renderApp()
    await openStaff()
    expect(await screen.findByRole('heading', { name: /preparing your cbt server/i })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/sync/status')).toBe(true)
    expect(screen.queryByRole('navigation', { name: /administrator navigation/i })).not.toBeInTheDocument()
  })

  it('lets teachers enter their workspace without an admin sync request', async () => {
    const fetchMock = routes({ 'POST /api/v1/auth/login': () => reply(teacher), 'GET /api/v1/questions/banks/authorable': () => reply([]) })
    renderApp()
    await openStaff()
    const teacherNavigation = await screen.findByRole('navigation', { name: /teacher navigation/i })
    expect(within(teacherNavigation).getByRole('button', { name: /question banks/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /good (morning|afternoon|evening), mrs\./i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /quick actions/i }))
    expect(screen.getByRole('menu', { name: /teacher quick actions/i })).toBeInTheDocument()
    expect(await screen.findByText(/no draft exams right now/i)).toBeInTheDocument()
    expect(within(screen.getByLabelText(/teacher workspace summary/i)).queryByText('320')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/sync/status')).toBe(false)
  })

  it('shows recoverable backend sync errors and retries without forcing full bootstrap', async () => {
    const fetchMock = routes({
      'POST /api/v1/auth/login': () => reply(admin),
      'GET /api/v1/sync/status': () => reply({ ...incomplete, last_error: 'School connection unavailable' }),
      'POST /api/v1/sync/reconcile': () => reply(incomplete),
    })
    renderApp()
    await openStaff()
    expect(await screen.findByText(/school connection unavailable/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry synchronization/i }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/sync/reconcile')).toBe(true))
    expect(fetchMock.mock.calls.some(([url]) => url.includes('force_full=true'))).toBe(false)
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument()
  })

  it('stays on initial sync until a later poll reports completed bootstrap', async () => {
    let reads = 0
    const fetchMock = routes({
      'POST /api/v1/auth/login': () => reply(admin),
      'GET /api/v1/sync/status': () => reply(++reads === 1 ? incomplete : complete),
    })
    renderApp()
    await openStaff()
    expect(await screen.findByRole('heading', { name: /preparing your cbt server/i })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: /administrator navigation/i })).not.toBeInTheDocument()
    expect(await screen.findByRole('navigation', { name: /administrator navigation/i }, { timeout: 4000 })).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/v1/sync/status').length).toBeGreaterThan(1)
  })
})
