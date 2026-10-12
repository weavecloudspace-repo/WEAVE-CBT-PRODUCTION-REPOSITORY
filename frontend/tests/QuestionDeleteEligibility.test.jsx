import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TeacherQuestionsPage } from '../src/features/teacher/TeacherQuestionsPage'
import { QuestionsPage } from '../src/features/teacher/QuestionsPage'

describe.each([TeacherQuestionsPage, QuestionsPage])('question delete visibility', (Page) => {
  it.each([true, false, undefined])('requires explicit deletion eligibility: %s', (canDelete) => {
    const question = { id: 'q1', bankId: 'b1', bankName: 'English', prompt: 'What is a noun?', type: 'Single choice', status: 'Ready', version: 1, options: [], canDelete }
    render(<Page state={{ staff: {} }} dispatch={vi.fn()} teacherData={{ banks: [{ id: 'b1', name: 'English', status: 'Ready' }], questions: [question] }} gateway={{ questions: {} }} />)
    fireEvent.click(screen.getByRole('button', { name: /question lifecycle for what is a noun/i }))
    const deletion = screen.queryByRole('button', { name: /delete permanently/i })
    if (canDelete === true) expect(deletion).toBeInTheDocument()
    else expect(deletion).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /archive question/i })).toBeInTheDocument()
  })
})
