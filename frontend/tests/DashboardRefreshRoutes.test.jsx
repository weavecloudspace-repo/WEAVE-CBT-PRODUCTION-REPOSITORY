import { act, renderHook, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAppController } from '../src/app/useAppController'

function makeGateway(role) {
  return {
    branding: { getBranding: vi.fn().mockResolvedValue({}) },
    installation: { getInstallationStatus: vi.fn().mockResolvedValue({ configured: true }) },
    auth: { refreshStaff: vi.fn().mockResolvedValue({ type: 'staff', role, actor: { role } }), clearStaffSession: vi.fn() },
    sync: { getSyncStatus: vi.fn().mockResolvedValue({ bootstrap_completed_at: '2026-09-01' }) },
  }
}
beforeEach(() => window.localStorage.clear())

const sharedRoutes = [
  ['questions/q-42/edit', 'edit-question', { selectedQuestionId: 'q-42' }],
  ['questions/q-42/preview?from=create-exam&exam=e-42', 'preview-question', { selectedQuestionId: 'q-42', selectedExamId: 'e-42', questionPreviewOrigin: 'create-exam' }],
  ['exams/e-42/edit', 'create-exam', { selectedExamId: 'e-42' }],
  ['exams/e-42/history', 'exam-history', { selectedExamId: 'e-42' }],
  ['question-banks/b-42', 'bank-detail', { selectedBankId: 'b-42' }],
  ['create-question?bank=b-42', 'create-question', { selectedBankId: 'b-42' }],
  ['create-exam', 'create-exam', { selectedExamId: null }],
  ['questions', 'questions', {}],
]
describe.each(['teacher', 'admin'])('%s dashboard refresh', (role) => {
  it.each(sharedRoutes)('restores %s instead of stale saved navigation', async (path, section, selected) => {
    window.history.replaceState({}, '', `/${role}/${path}`)
    window.localStorage.setItem('weave.cbt.navigation', JSON.stringify({ sessionType: 'staff', role, staffSection: 'create-question', selectedQuestionId: 'stale' }))
    const gateway = makeGateway(role)
    const { result } = renderHook(() => useAppController({ application: 'staff', gateway }), { wrapper: BrowserRouter })
    await waitFor(() => expect(result.current.state.view).toBe('staff'))
    expect(result.current.state.staff).toMatchObject({ section, ...selected })
    expect(window.location.pathname + window.location.search).toBe(`/${role}/${path}`)
  })
})
it.each([['roster', 'roster-detail'], ['operations', 'operation-detail'], ['results', 'result-detail']])('restores the admin %s detail record', async (path, section) => {
  window.history.replaceState({}, '', `/admin/exams/e-42/${path}`)
  const gateway = makeGateway('admin')
  const { result } = renderHook(() => useAppController({ application: 'staff', gateway }), { wrapper: BrowserRouter })
  await waitFor(() => expect(result.current.state.view).toBe('staff'))
  expect(result.current.state.staff).toMatchObject({ section, selectedExamId: 'e-42' })
  expect(window.location.pathname).toBe(`/admin/exams/e-42/${path}`)
})
it('waits for session restoration without replacing a deep link with the login page', async () => {
  window.history.replaceState({}, '', '/teacher/questions/q-42/edit')
  const gateway = makeGateway('teacher')
  let resolveSession
  gateway.auth.refreshStaff.mockReturnValue(new Promise((resolve) => { resolveSession = resolve }))
  const { result } = renderHook(() => useAppController({ application: 'staff', gateway }), { wrapper: BrowserRouter })
  await waitFor(() => expect(gateway.auth.refreshStaff).toHaveBeenCalled())
  expect(window.location.pathname).toBe('/teacher/questions/q-42/edit')
  await act(async () => resolveSession({ type: 'staff', role: 'teacher', actor: { role: 'teacher' } }))
  await waitFor(() => expect(result.current.state.view).toBe('staff'))
  expect(result.current.state.staff.selectedQuestionId).toBe('q-42')
})
it('keeps exam identity in preview navigation and returns to the same editor', async () => {
  window.history.replaceState({}, '', '/admin/exams/e-42/edit')
  const gateway = makeGateway('admin')
  const { result } = renderHook(() => useAppController({ application: 'staff', gateway }), { wrapper: BrowserRouter })
  await waitFor(() => expect(result.current.state.view).toBe('staff'))
  act(() => result.current.dispatch({ type: 'staff', patch: { section: 'preview-question', selectedQuestionId: 'q-42', questionPreviewOrigin: 'create-exam' } }))
  await waitFor(() => expect(window.location.pathname).toBe('/admin/questions/q-42/preview'))
  expect(new URLSearchParams(window.location.search).get('exam')).toBe('e-42')
  act(() => result.current.dispatch({ type: 'staff', patch: { section: 'create-exam', selectedQuestionId: null, questionPreviewOrigin: null } }))
  await waitFor(() => expect(window.location.pathname).toBe('/admin/exams/e-42/edit'))
})
