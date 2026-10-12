import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { EditQuestionPage } from '../src/features/teacher/EditQuestionPage'
import { QuestionsPage } from '../src/features/teacher/QuestionsPage'

const bank = { id: 'bank-1', name: 'JSS1 ENGLISH', status: 'Ready' }

const rawQuestion = {
  id: 'question-1',
  bank_id: bank.id,
  question_type: 'single_choice',
  prompt: 'What is a noun?',
  instruction: 'Choose the best answer.',
  image_asset_id: null,
  version: 2,
  is_active: true,
  options: [
    { id: 'option-1', text: 'A naming word', is_correct: true },
    { id: 'option-2', text: 'An action word', is_correct: false },
  ],
}

describe('Teacher question editing', () => {
  it('loads the selected backend question into a real edit page and saves changes', async () => {
    const dispatch = vi.fn()
    const refresh = vi.fn().mockResolvedValue(undefined)
    const getQuestion = vi.fn().mockResolvedValue(rawQuestion)
    const updateQuestion = vi.fn().mockResolvedValue({ ...rawQuestion, version: 3 })

    render(
      <EditQuestionPage
        state={{ staff: { section: 'edit-question', selectedQuestionId: rawQuestion.id, editingQuestion: null } }}
        dispatch={dispatch}
        teacherData={{ banks: [bank], questions: [], refresh }}
        gateway={{
          questions: { getQuestion, updateQuestion },
          media: { uploadQuestionImage: vi.fn() },
        }}
      />,
    )

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Edit Question' })).toBeInTheDocument())
    expect(getQuestion).toHaveBeenCalledWith(rawQuestion.id)
    expect(screen.getByLabelText('Question prompt')).toHaveValue('What is a noun?')
    expect(screen.getByLabelText('Question Bank')).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Question prompt'), { target: { value: 'Which option is a noun?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(updateQuestion).toHaveBeenCalledWith(rawQuestion.id, {
      prompt: 'Which option is a noun?',
      instruction: 'Choose the best answer.',
      options: [
        { text: 'A naming word', is_correct: true },
        { text: 'An action word', is_correct: false },
      ],
    }))
    expect(refresh).toHaveBeenCalled()
    expect(dispatch).toHaveBeenCalledWith({
      type: 'staff',
      patch: { section: 'questions', selectedQuestionId: null, editingQuestion: null },
    })
  })
})

describe('Teacher question lifecycle deletion', () => {
  it('opens a centered confirmation modal before deleting an unused question', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined)
    const deleteUnusedQuestion = vi.fn().mockResolvedValue(undefined)
    const question = {
      id: rawQuestion.id,
      bankId: bank.id,
      bankName: bank.name,
      prompt: rawQuestion.prompt,
      instruction: rawQuestion.instruction,
      type: 'Single choice',
      image: false,
      status: 'Ready',
      canDelete: true,
      version: 2,
      options: rawQuestion.options,
    }

    render(
      <QuestionsPage
        dispatch={vi.fn()}
        teacherData={{ banks: [bank], questions: [question], loading: false, error: '', refresh }}
        gateway={{
          questions: {
            archiveQuestion: vi.fn(),
            reactivateQuestion: vi.fn(),
            deleteUnusedQuestion,
          },
        }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /question lifecycle for what is a noun/i }))
    fireEvent.click(screen.getByRole('button', { name: /delete permanently/i }))

    expect(deleteUnusedQuestion).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog', { name: /delete this question permanently/i })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /confirm delete/i }))
    await waitFor(() => expect(deleteUnusedQuestion).toHaveBeenCalledWith(question.id))
    expect(refresh).toHaveBeenCalled()
  })
})
