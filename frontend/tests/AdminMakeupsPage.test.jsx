import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { AdminMakeupsPage } from '../src/features/admin/pages/AdminMakeupsPage'
import { ToastHost } from '../src/shared/ui/ToastHost'
import { toastBus } from '../src/shared/ui/useToast'

afterEach(() => toastBus.clear())

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
const exam = { id: 'exam', title: 'English Test', subjectName: 'English', academicLevelId: 'level', academicLevelName: 'JSS1', status: 'closed' }
const data = { exams: [exam] }
const row = (id, overrides = {}) => ({ id, name: id, admission_number: id, class_name: 'JSS1 A', state: 'awaiting_approval', can_approve: true, can_revoke: false, percentage: null, ...overrides })
function gateway(rows = [row('Ada'), row('Bola')]) {
  return { makeups: {
    listMakeupReviewSets: vi.fn().mockResolvedValue({ exams: [{ exam_id: 'exam', awaiting_approval: 2 }] }),
    getMakeupReview: vi.fn().mockResolvedValue({ candidates: rows, total: rows.length, blockers: ['Mathematics Test'], fresh_question_count: 25, required_question_count: 20, available: false }),
    approveMakeup: vi.fn().mockResolvedValue({}), revokeMakeup: vi.fn().mockResolvedValue({}),
  } }
}

it('opens the dedicated review for a closed exam', async () => {
  const onNavigate = vi.fn()
  render(<AdminMakeupsPage adminData={data} gateway={gateway()} onNavigate={onNavigate} />)
  fireEvent.click(await screen.findByRole('button', { name: /manage makeups/i }))
  expect(onNavigate).toHaveBeenCalledWith('makeup-detail', { selectedExamId: 'exam' })
})

it('shows blockers and approves selected missed students with a reason, then clears selection', async () => {
  const api = gateway()
  render(<AdminMakeupsPage examId="exam" adminData={data} gateway={api} onNavigate={vi.fn()} />)
  expect(await screen.findByText(/Normal examinations still unfinished: Mathematics Test/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Select all eligible' }))
  fireEvent.click(screen.getByRole('button', { name: 'Approve selected (2)' }))
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Approved absence' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm approval' }))
  await waitFor(() => expect(api.makeups.approveMakeup).toHaveBeenCalledTimes(2))
  expect(api.makeups.approveMakeup).toHaveBeenCalledWith('Ada', 'Approved absence', { successMessage: false })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Approve selected (0)' })).toBeDisabled())
})

it('keeps a started makeup out of approval and revocation actions', async () => {
  render(<AdminMakeupsPage examId="exam" adminData={data} gateway={gateway([row('Ada', { state: 'writing', can_approve: false, remaining_seconds: 1200 })])} onNavigate={vi.fn()} />)
  expect(await screen.findByText('20 min remaining')).toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: 'Select Ada' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
})

it('reports partial approvals and clears bulk mode instead of reporting total success', async () => {
  const api = gateway()
  api.makeups.approveMakeup.mockRejectedValueOnce({ userMessage: 'Already started.' }).mockResolvedValueOnce({})
  render(<><AdminMakeupsPage examId="exam" adminData={data} gateway={api} onNavigate={vi.fn()} /><ToastHost /></>)
  await screen.findByRole('checkbox', { name: 'Select Ada' })
  fireEvent.click(screen.getByRole('button', { name: 'Select all eligible' }))
  fireEvent.click(screen.getByRole('button', { name: 'Approve selected (2)' }))
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Absent' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm approval' }))
  expect(await screen.findByText('Ada: Already started.')).toBeInTheDocument()
  expect(screen.getByText('1 makeup approval granted.')).toBeInTheDocument()
})
