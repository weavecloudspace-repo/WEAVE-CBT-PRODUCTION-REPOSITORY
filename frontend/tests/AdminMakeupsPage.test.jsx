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
const exam = { id: 'exam', title: 'English Test', subjectName: 'English', academicLevelId: 'level', academicLevelName: 'JSS1', assessmentName: 'Test 1', status: 'closed' }
const data = { exams: [exam] }
const row = (id, overrides = {}) => ({ id, name: id, admission_number: id, class_name: 'JSS1 A', state: 'awaiting_approval', can_approve: true, can_revoke: false, percentage: null, ...overrides })
function gateway(rows = [row('Ada'), row('Bola')]) {
  return { makeups: {
    listMakeupReviewSets: vi.fn().mockResolvedValue({ eligible_exam_ids: ['exam'], exams: [{ exam_id: 'exam', awaiting_approval: 2 }] }),
    getMakeupReview: vi.fn().mockResolvedValue({ candidates: rows, total: rows.length, blockers: ['Mathematics Test'], fresh_question_count: 25, required_question_count: 20, available: false }),
    addMakeupStudent: vi.fn().mockResolvedValue({}), approveMakeup: vi.fn().mockResolvedValue({}), revokeMakeup: vi.fn().mockResolvedValue({}),
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


it('adds a new student from the exam list and opens the makeup review', async () => {
  const api = gateway()
  const onNavigate = vi.fn()
  render(<AdminMakeupsPage adminData={data} gateway={api} onNavigate={onNavigate} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Add student' }))
  expect(screen.getByRole('button', { name: 'Add and authorize' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Admission number'), { target: { value: ' NEW001 ' } })
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Joined after Test 1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add and authorize' }))
  await waitFor(() => expect(api.makeups.addMakeupStudent).toHaveBeenCalledWith('exam', 'NEW001', 'Joined after Test 1'))
  expect(onNavigate).toHaveBeenCalledWith('makeup-detail', { selectedExamId: 'exam' })
})

it('shows only backend-eligible current-term exams and filters assessment components', async () => {
  const api = gateway()
  api.makeups.listMakeupReviewSets.mockResolvedValue({ eligible_exam_ids: ['exam', 'exam2'], exams: [] })
  const other = { ...exam, id: 'exam2', title: 'English Test 2', assessmentName: 'Test 2' }
  render(<AdminMakeupsPage adminData={{ exams: [exam, other, { ...exam, id: 'past', title: 'Last term exam' }] }} gateway={api} onNavigate={vi.fn()} />)
  await screen.findByText('English Test 2')
  expect(screen.queryByText('Last term exam')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('combobox', { name: 'Assessment component' }))
  fireEvent.click(screen.getByRole('option', { name: 'Test 1' }))
  expect(screen.getByText('English Test')).toBeInTheDocument()
  expect(screen.queryByText('English Test 2')).not.toBeInTheDocument()
})

it('keeps the add dialog and entered details when enrollment validation fails', async () => {
  const api = gateway()
  api.makeups.addMakeupStudent.mockRejectedValue({ userMessage: 'Student is outside the exam scope.' })
  render(<AdminMakeupsPage adminData={data} gateway={api} onNavigate={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Add student' }))
  fireEvent.change(screen.getByLabelText('Admission number'), { target: { value: '001' } })
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'New enrollee' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add and authorize' }))
  expect(await screen.findByText('Student is outside the exam scope.')).toBeVisible()
  expect(screen.getByLabelText('Admission number')).toHaveValue('001')
})
