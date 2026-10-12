import { useState } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { StudentWorkspace } from '../src/features/student/StudentWorkspace'
import { ToastHost } from '../src/shared/ui/ToastHost'

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
})

function setup({ suspended = false, save, stage = 'active', availability = 'ready', onSuspended = vi.fn(), attemptOverride = {}, heartbeat, load, submit, returnToSignIn = vi.fn() } = {}) {
  const question = { id: 'q1', prompt: 'First question', question_type: 'single_choice', selected_option_ids: ['a'], is_flagged: false, mutation_sequence: 1, options: [{ id: 'a', text: 'First answer' }, { id: 'b', text: 'Second answer' }] }
  const attempt = {
    id: 'attempt',
    exam_title: 'English exam',
    status: 'in_progress',
    time_limit_seconds: 2700,
    remaining_seconds: 2700,
    exam_suspended: suspended,
    questions: [question, { ...question, id: 'q2', prompt: 'Second question', selected_option_ids: [] }],
    ...attemptOverride,
  }
  const gateway = {
    auth: { getStudentStatus: vi.fn().mockResolvedValue({ availability, exam_id: 'exam', status_message: 'Please wait for your invigilator.' }) },
    attempts: {
      getCurrentAttempt: load || vi.fn().mockResolvedValue(attempt),
      startCurrentAttempt: vi.fn().mockResolvedValue(attempt),
      submitCurrentAttempt: submit || vi.fn().mockResolvedValue({}),
      heartbeatCurrentAttempt: heartbeat || vi.fn().mockResolvedValue({ status: attempt.status, remaining_seconds: attempt.remaining_seconds, exam_suspended: suspended, next_heartbeat_after_seconds: 20 }),
      saveCurrentAnswer: save || vi.fn(async (_id, payload) => ({ ...payload, remaining_seconds: 2699 })),
    },
  }
  function Harness() {
    const [exam, setExam] = useState({ stage, index: 0 })
    return <StudentWorkspace exam={exam} resolution={{ state: 'ready', exam: { id: 'exam', title: 'English exam' }, candidate: { name: 'Ada' } }} onExamSuspended={onSuspended} serverName="Debright hall server 1" gateway={gateway} dispatch={({ patch }) => setExam((current) => ({ ...current, ...patch }))} returnToSignIn={returnToSignIn} branding={{ school_name: 'Debright college', is_enabled: true, logo_path: 'school.png', logo_revision: '3' }} />
  }
  render(<Harness />)
  return { gateway, returnToSignIn }
}

afterEach(() => vi.useRealTimers())

it('keeps the shared CBT loader visible until the active exam opens, with retry on failure', async () => {
  render(<ToastHost />)
  let openAttempt
  const load = vi.fn()
    .mockRejectedValueOnce({ userMessage: 'The exam could not be loaded.' })
    .mockImplementationOnce(() => new Promise((resolve) => { openAttempt = resolve }))
  setup({ load })
  expect(screen.getByRole('heading', { name: 'Starting Weave' })).toBeInTheDocument()
  expect(screen.queryByText('Loading exam')).not.toBeInTheDocument()
  expect(screen.queryByText('Weave is opening your active attempt.')).not.toBeInTheDocument()
  await screen.findByText('The exam could not be loaded.')
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2))
  expect(screen.getByRole('heading', { name: 'Starting Weave' })).toBeInTheDocument()
  await act(async () => openAttempt({ id: 'attempt', status: 'in_progress', remaining_seconds: 2700, time_limit_seconds: 2700, questions: [{ id: 'q1', prompt: 'Restored question', question_type: 'single_choice', selected_option_ids: [], options: [] }] }))
  expect(await screen.findByText('Restored question')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Starting Weave' })).not.toBeInTheDocument()
})

it('warns about unanswered questions and only submits after confirmation', async () => {
  const { gateway } = setup()
  await screen.findByText('First question')
  fireEvent.click(screen.getByRole('button', { name: 'Submit exam' }))
  expect(screen.getByRole('dialog', { name: 'Confirm exam submission' })).toHaveTextContent('You have not answered 1 question.')
  expect(gateway.attempts.submitCurrentAttempt).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save and next' }))
  fireEvent.click(screen.getAllByRole('button', { name: 'Submit exam' })[1])
  fireEvent.click(screen.getByRole('button', { name: 'Confirm submission' }))
  await screen.findByRole('heading', { name: 'Exam submitted' })
  expect(gateway.attempts.submitCurrentAttempt).toHaveBeenCalledOnce()
})

it('still asks for confirmation when every question is answered', async () => {
  const { gateway } = setup()
  await screen.findByText('First question')
  fireEvent.click(screen.getByRole('button', { name: 'Save and next' }))
  fireEvent.click(screen.getByRole('radio', { name: 'Option A: First answer' }))
  await waitFor(() => expect(screen.getByRole('radio', { name: 'Option A: First answer' })).not.toBeDisabled())
  fireEvent.click(screen.getAllByRole('button', { name: 'Submit exam' })[0])
  expect(screen.getByRole('dialog')).toHaveTextContent('You have answered all questions. Are you sure you want to submit?')
  fireEvent.click(screen.getByRole('button', { name: 'Confirm submission' }))
  await screen.findByRole('heading', { name: 'Exam submitted' })
  expect(gateway.attempts.submitCurrentAttempt).toHaveBeenCalledOnce()
})

it('uses school branding and clean navigation labels', async () => {
  setup()
  await screen.findByText('First question')
  expect(screen.getByText('Debright college')).toBeInTheDocument()
  expect(screen.queryByText('Debright hall server 1')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 1, name: 'English exam' })).toBeInTheDocument()
  expect(document.querySelector('.student-avatar')).toHaveTextContent('A')
  expect(document.querySelector('.dashboard-school-identity img').src).toContain('/branding/logo?v=3')
  expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Save and next' })).toBeInTheDocument()
})

it('counts down between heartbeats and resynchronizes with the server', async () => {
  vi.useFakeTimers()
  const { gateway } = setup()
  await act(async () => { await Promise.resolve() })
  expect(screen.getByText('45:00')).toBeInTheDocument()
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(screen.getByText('44:57')).toBeInTheDocument()
  gateway.attempts.heartbeatCurrentAttempt.mockResolvedValue({ status: 'in_progress', remaining_seconds: 2670, exam_suspended: false, next_heartbeat_after_seconds: 20 })
  await act(async () => { await vi.advanceTimersByTimeAsync(17000) })
  expect(screen.getByText('44:30')).toBeInTheDocument()
})

it('blocks a suspended restored attempt and requests suspension handling once', async () => {
  const onSuspended = vi.fn()
  setup({ suspended: true, onSuspended })
  await screen.findByRole('heading', { name: 'Exam currently suspended' })
  expect(screen.queryByText('First question')).not.toBeInTheDocument()
  expect(onSuspended).toHaveBeenCalledOnce()
})

it('persists review flags without replacing answers and shows them across navigation', async () => {
  const { gateway } = setup()
  const mark = await screen.findByRole('checkbox', { name: 'Mark for review' })
  fireEvent.click(mark)
  await waitFor(() => expect(mark).not.toBeDisabled())
  expect(gateway.attempts.saveCurrentAnswer).toHaveBeenCalledWith('q1', { mutation_sequence: 2, selected_option_ids: ['a'], is_flagged: true })
  expect(screen.getByRole('button', { name: 'Question 1, marked for review' })).toHaveClass('flagged')
  fireEvent.click(screen.getByRole('button', { name: 'Save and next' }))
  fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
  expect(screen.getByRole('checkbox', { name: 'Mark for review' })).toBeChecked()
})

it('rolls back review marking when saving fails', async () => {
  setup({ save: vi.fn().mockRejectedValue(new Error('offline')) })
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Mark for review' }))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Mark for review' })).not.toBeChecked())
  expect(screen.getByRole('button', { name: 'Question 1' })).not.toHaveClass('flagged')
})

it('detects suspension during a live heartbeat and removes exam controls', async () => {
  vi.useFakeTimers()
  const onSuspended = vi.fn()
  const { gateway } = setup({ onSuspended })
  await act(async () => { await Promise.resolve() })
  gateway.attempts.heartbeatCurrentAttempt.mockResolvedValue({ status: 'in_progress', remaining_seconds: 2680, exam_suspended: true, next_heartbeat_after_seconds: 20 })
  await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
  expect(onSuspended).toHaveBeenCalledOnce()
  expect(screen.queryByText('First question')).not.toBeInTheDocument()
})

it('checks live availability before starting an active exam', async () => {
  const { gateway } = setup({ stage: 'lobby' })
  fireEvent.click(screen.getByRole('button', { name: /Start Exam/ }))
  await screen.findByText('First question')
  expect(gateway.auth.getStudentStatus).toHaveBeenCalledOnce()
  expect(gateway.attempts.startCurrentAttempt).toHaveBeenCalledOnce()
  expect(gateway.auth.getStudentStatus.mock.invocationCallOrder[0]).toBeLessThan(gateway.attempts.startCurrentAttempt.mock.invocationCallOrder[0])
})

it('does not start an exam that has become suspended', async () => {
  const onSuspended = vi.fn()
  const { gateway } = setup({ stage: 'lobby', availability: 'suspended', onSuspended })
  fireEvent.click(screen.getByRole('button', { name: /Start Exam/ }))
  await waitFor(() => expect(onSuspended).toHaveBeenCalledOnce())
  expect(gateway.attempts.startCurrentAttempt).not.toHaveBeenCalled()
})

it('handles suspension between the availability check and the start request', async () => {
  const onSuspended = vi.fn()
  const { gateway } = setup({ stage: 'lobby', onSuspended })
  gateway.attempts.startCurrentAttempt.mockRejectedValue(new Error('suspended'))
  gateway.auth.getStudentStatus.mockResolvedValueOnce({ availability: 'ready', exam_id: 'exam' }).mockResolvedValue({ availability: 'suspended', exam_id: 'exam', status_message: 'Exam paused.' })
  fireEvent.click(screen.getByRole('button', { name: /Start Exam/ }))
  await waitFor(() => expect(onSuspended).toHaveBeenCalledWith('Exam paused.'))
})

it('does not start if the availability check fails', async () => {
  const { gateway } = setup({ stage: 'lobby' })
  gateway.auth.getStudentStatus.mockRejectedValue(new Error('offline'))
  fireEvent.click(screen.getByRole('button', { name: /Start Exam/ }))
  await waitFor(() => expect(screen.getByRole('button', { name: /Start Exam/ })).not.toBeDisabled())
  expect(gateway.attempts.startCurrentAttempt).not.toHaveBeenCalled()
})

it('shows an explicit paused state for interrupted attempts and removes answer controls', async () => {
  const heartbeat = vi.fn().mockResolvedValue({ status: 'interrupted', remaining_seconds: 1800, exam_suspended: false, next_heartbeat_after_seconds: 20 })
  setup({ attemptOverride: { status: 'interrupted', remaining_seconds: 1800 }, heartbeat })
  expect(await screen.findByRole('heading', { name: 'Your examination has been paused' })).toBeInTheDocument()
  expect(screen.getByText(/timer is paused/i)).toBeInTheDocument()
  expect(screen.queryByText('First question')).not.toBeInTheDocument()
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
})

it('automatically submits at zero without asking for candidate confirmation', async () => {
  let finishSubmission
  const submit = vi.fn(() => new Promise((resolve) => { finishSubmission = resolve }))
  const { gateway } = setup({ attemptOverride: { remaining_seconds: 0 }, submit })
  expect(await screen.findByRole('heading', { name: 'Time is up' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: 'Confirm exam submission' })).not.toBeInTheDocument()
  await waitFor(() => expect(gateway.attempts.submitCurrentAttempt).toHaveBeenCalledOnce())
  await act(async () => finishSubmission({}))
  expect(await screen.findByRole('heading', { name: 'Exam submitted' })).toBeInTheDocument()
})

it('warns that logging out does not pause an active attempt', async () => {
  setup()
  await screen.findByText('First question')
  fireEvent.click(screen.getByRole('button', { name: 'Logout' }))
  const dialog = screen.getByRole('dialog', { name: 'Log out during examination?' })
  expect(dialog).toHaveTextContent('timer will continue running while you are logged out')
})

it('leaves a stale exam screen when the server reports the student session is terminal', async () => {
  const returnToSignIn = vi.fn()
  const heartbeat = vi.fn().mockRejectedValue(Object.assign(new Error('unauthorized'), { status: 401 }))
  setup({ heartbeat, returnToSignIn })
  await screen.findByText('First question')
  await waitFor(() => expect(returnToSignIn).toHaveBeenCalledOnce())
})
