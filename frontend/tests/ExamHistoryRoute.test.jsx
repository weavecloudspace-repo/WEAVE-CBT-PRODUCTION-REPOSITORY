import { act, renderHook, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { useAppController } from '../src/app/useAppController'

beforeEach(() => { window.localStorage.clear() })

it.each(['admin', 'teacher'])('restores an examination history URL for %s and retains the selected exam', async (role) => {
  window.history.replaceState({}, '', `/${role}/exams/exam-42/history`)
  const gateway = {
    branding: { getBranding: vi.fn().mockResolvedValue({}) },
    installation: { getInstallationStatus: vi.fn().mockResolvedValue({ configured: true }) },
    auth: { refreshStaff: vi.fn().mockResolvedValue({ type: 'staff', role, actor: { role } }), clearStaffSession: vi.fn() },
    sync: { getSyncStatus: vi.fn().mockResolvedValue({ bootstrap_completed_at: '2026-09-01' }) },
  }
  const { result } = renderHook(() => useAppController({ application: 'staff', gateway }), { wrapper: BrowserRouter })
  await waitFor(() => expect(result.current.state.staff.selectedExamId).toBe('exam-42'))
  await waitFor(() => expect(result.current.state.view).toBe('staff'))
  expect(result.current.state.staff.section).toBe('exam-history')
  expect(window.location.pathname).toBe(`/${role}/exams/exam-42/history`)
  act(() => result.current.dispatch({ type: 'staff', patch: { section: 'exam-history', selectedExamId: 'exam-43' } }))
  await waitFor(() => expect(window.location.pathname).toBe(`/${role}/exams/exam-43/history`))
  expect(result.current.state.staff.selectedExamId).toBe('exam-43')
})
