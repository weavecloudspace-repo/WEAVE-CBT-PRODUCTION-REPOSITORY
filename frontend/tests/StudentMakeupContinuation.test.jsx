import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { StudentMakeupContinuation } from '../src/features/student/StudentMakeupContinuation'

it('offers the next approved makeup and binds its lobby without signing out', async () => {
  const dispatch = vi.fn()
  const onContinue = vi.fn()
  render(<StudentMakeupContinuation gateway={{ auth: { getStudentStatus: vi.fn().mockResolvedValue({ availability: 'makeup', exam_id: 'next', exam_title: 'Literature Test', subject_name: 'Literature', duration_minutes: 60, is_makeup: true, display_name: 'Ada' }) } }} dispatch={dispatch} onContinue={onContinue} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Continue to next makeup' }))
  expect(onContinue).toHaveBeenCalledOnce()
  expect(dispatch).toHaveBeenCalledWith({ type: 'exam', patch: { stage: 'lobby', index: 0 } })
  expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: 'studentResolution', resolution: expect.objectContaining({ isMakeup: true, exam: expect.objectContaining({ id: 'next', subjectName: 'Literature' }) }) }))
})

it('shows the server waiting reason when there is no available next paper', async () => {
  render(<StudentMakeupContinuation gateway={{ auth: { getStudentStatus: vi.fn().mockResolvedValue({ availability: 'no_exam', status_message: 'All approved papers completed.' }) } }} dispatch={vi.fn()} />)
  expect(await screen.findByText('All approved papers completed.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Continue to next makeup' })).not.toBeInTheDocument()
})
