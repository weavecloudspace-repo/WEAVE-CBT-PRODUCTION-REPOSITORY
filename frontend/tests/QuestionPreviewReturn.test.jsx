import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TeacherQuestionPreviewPage } from '../src/features/teacher/TeacherQuestionPreviewPage'

describe('question preview return navigation', () => {
  it.each(['teacher', 'admin'])('returns %s authors to their exam form even when the preview cannot load', async (role) => {
    const dispatch = vi.fn()
    render(<TeacherQuestionPreviewPage
      state={{ session: { actor: { role } }, staff: { selectedQuestionId: 'q1', selectedExamId: 'exam-1', questionPreviewOrigin: 'create-exam' } }}
      dispatch={dispatch}
      teacherData={{ banks: [] }}
      gateway={{ questions: { getQuestion: vi.fn().mockRejectedValue(new Error('Offline')) } }}
    />)
    await waitFor(() => expect(screen.queryByText(/Loading question preview/)).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Back to exam form' }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: expect.objectContaining({ section: 'create-exam', selectedQuestionId: null, questionPreviewOrigin: null }) })
    expect(dispatch.mock.calls[0][0].patch).not.toHaveProperty('selectedExamId')
  })
})
