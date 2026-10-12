import { ToastHost } from '../src/shared/ui/ToastHost'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { StudentWorkspace } from '../src/features/student/StudentWorkspace'

const baseExamState = {
  stage: 'lobby',
  index: 0,
}

const gateway = {
  attempts: {
    getCurrentAttempt: vi.fn(),
    startCurrentAttempt: vi.fn(),
  },
}

function renderWaitingRoom(resolution) {
  render(<ToastHost />)
  render(
    <StudentWorkspace
      exam={baseExamState}
      resolution={resolution}
      gateway={gateway}
      dispatch={vi.fn()}
      returnToSignIn={vi.fn()}
    />,
  )
}

describe('student waiting room', () => {
  it('offers resume only after a suspended unfinished attempt becomes ready', async () => {
    const dispatch = vi.fn()
    const localGateway = {
      auth: { getStudentStatus: vi.fn().mockResolvedValue({ availability: 'ready', exam_id: 'exam' }) },
      attempts: { startCurrentAttempt: vi.fn().mockResolvedValue({ id: 'existing-attempt', status: 'in_progress', exam_suspended: false }) },
    }
    const resolution = {
      state: 'suspended',
      exam: { id: 'exam', title: 'Mathematics' },
      hasUnfinishedAttempt: true,
    }
    const workspace = (currentResolution) => (
      <StudentWorkspace exam={baseExamState} resolution={currentResolution}
        gateway={localGateway} dispatch={dispatch} returnToSignIn={vi.fn()} />
    )
    const view = render(workspace(resolution))
    expect(screen.getByRole('button', { name: 'Waiting for exam to resume...' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Resume attempt' })).not.toBeInTheDocument()

    view.rerender(workspace({ ...resolution, state: 'ready' }))
    expect(screen.getByRole('button', { name: 'Resume attempt' })).toBeEnabled()
    expect(screen.getByText('Ready to resume')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Resume attempt' }))
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'exam', patch: { stage: 'active', index: 0 } }))
    expect(localGateway.attempts.startCurrentAttempt).toHaveBeenCalledOnce()

    // An exam change must follow the new backend resolution, not remembered suspension.
    view.rerender(workspace({ state: 'ready', exam: { id: 'new-exam', title: 'English' }, hasUnfinishedAttempt: false }))
    expect(screen.getByRole('button', { name: 'Start Exam' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Resume attempt' })).not.toBeInTheDocument()
  })

  it('keeps an authenticated student in the waiting room when no exam exists', () => {
    renderWaitingRoom({
      state: 'no_exam',
      statusMessage: 'No examination is currently available for you.',
      exam: null,
      candidate: {
        id: null,
        name: 'Ada Okafor',
        studentId: '77777777-7777-7777-7777-777777777777',
      },
      isMakeup: false,
    })

    expect(screen.getByRole('heading', { name: /no exam available yet/i })).toBeInTheDocument()
    expect(screen.getByText(/no examination is currently available for you/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /waiting for an exam/i })).toBeDisabled()
    expect(screen.getByText(/you do not need to sign in again/i)).toBeInTheDocument()
  })

  it('shows a sealed exam as waiting for activation', () => {
    renderWaitingRoom({
      state: 'waiting_for_activation',
      statusMessage: 'Your examination is scheduled and waiting for activation.',
      exam: {
        id: '11111111-1111-1111-1111-111111111111',
        title: 'Mathematics CA1',
        scheduledStartAt: '2026-09-15T15:00:00Z',
      },
      candidate: {
        id: '22222222-2222-2222-2222-222222222222',
        name: 'Ada Okafor',
        studentId: '77777777-7777-7777-7777-777777777777',
      },
      isMakeup: false,
    })

    expect(screen.getByRole('heading', { name: /mathematics ca1/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /waiting for activation/i })).toBeDisabled()
  })

  it('enables the exam action only when the backend reports ready', () => {
    renderWaitingRoom({
      state: 'ready',
      statusMessage: 'Your examination is ready to begin.',
      exam: {
        id: '11111111-1111-1111-1111-111111111111',
        title: 'Mathematics CA1',
        scheduledStartAt: null,
      },
      candidate: {
        id: '22222222-2222-2222-2222-222222222222',
        name: 'Ada Okafor',
        studentId: '77777777-7777-7777-7777-777777777777',
      },
      isMakeup: false,
    })

    expect(screen.getByRole('button', { name: /start exam/i })).toBeEnabled()
  })
})
