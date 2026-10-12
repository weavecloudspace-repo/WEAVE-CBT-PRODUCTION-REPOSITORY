import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CreateQuestionPage, QuestionsPage } from '../src/features/teacher/QuestionsPage'

const bank = { id: 'bank-1', name: 'Mathematics', count: 0, status: 'Ready' }

describe('Teacher questions', () => {
  it('renders the question list and confirms lifecycle actions before calling the backend', async () => {
    const dispatch = vi.fn()
    const refresh = vi.fn().mockResolvedValue(undefined)
    const archiveQuestion = vi.fn().mockResolvedValue({})
    const question = {
      id: 'question-1',
      bankId: bank.id,
      bankName: bank.name,
      prompt: 'What is 2 + 2?',
      instruction: null,
      type: 'Single choice',
      image: false,
      status: 'Ready',
      version: 1,
      updated: 'v1',
      options: [],
    }

    render(
      <QuestionsPage
        dispatch={dispatch}
        teacherData={{ banks: [bank], questions: [question], loading: false, error: '', refresh }}
        gateway={{
          questions: {
            archiveQuestion,
            reactivateQuestion: vi.fn(),
            deleteUnusedQuestion: vi.fn(),
          },
        }}
      />,
    )

    expect(screen.getByRole('heading', { name: 'What is 2 + 2?' })).toBeInTheDocument()
    expect(screen.getAllByText('Mathematics').length).toBeGreaterThan(0)
    expect(screen.getByText('v1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    expect(dispatch).toHaveBeenCalledWith({
      type: 'staff',
      patch: {
        section: 'edit-question',
        selectedBankId: bank.id,
        selectedQuestionId: question.id,
        editingQuestion: question,
      },
    })

    fireEvent.click(screen.getByRole('button', { name: /question lifecycle for what is 2 \+ 2/i }))
    expect(screen.getByRole('dialog', { name: /lifecycle for what is 2 \+ 2/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /archive question/i }))

    expect(archiveQuestion).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog', { name: /archive this question/i })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /confirm archive/i }))

    await waitFor(() => expect(archiveQuestion).toHaveBeenCalledWith(question.id))
    expect(refresh).toHaveBeenCalled()
  })

  it('uploads a selected image and sends its asset id with the question payload', async () => {
    const dispatch = vi.fn()
    const refresh = vi.fn().mockResolvedValue(undefined)
    const uploadQuestionImage = vi.fn().mockResolvedValue({ id: 'asset-1' })
    const createSingleChoiceQuestion = vi.fn().mockResolvedValue({ id: 'question-1' })

    render(
      <CreateQuestionPage
        state={{ staff: { section: 'create-question', selectedBankId: bank.id } }}
        dispatch={dispatch}
        teacherData={{ banks: [bank], questions: [], refresh }}
        gateway={{
          media: { uploadQuestionImage },
          questions: { createSingleChoiceQuestion, createMultipleChoiceQuestion: vi.fn() },
        }}
      />,
    )

    const image = new File(['image-bytes'], 'diagram.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText(/choose image/i), { target: { files: [image] } })
    fireEvent.change(screen.getByLabelText(/question prompt/i), { target: { value: 'What does the diagram show?' } })
    fireEvent.change(screen.getByRole('textbox', { name: /^option a$/i }), { target: { value: 'A cell' } })
    fireEvent.change(screen.getByRole('textbox', { name: /^option b$/i }), { target: { value: 'A planet' } })
    fireEvent.click(screen.getByRole('button', { name: /save question/i }))

    await waitFor(() => expect(uploadQuestionImage).toHaveBeenCalledWith(image))
    expect(createSingleChoiceQuestion).toHaveBeenCalledWith(bank.id, {
      prompt: 'What does the diagram show?',
      instruction: null,
      image_asset_id: 'asset-1',
      options: [
        { text: 'A cell', is_correct: true },
        { text: 'A planet', is_correct: false },
      ],
    })
    expect(refresh).toHaveBeenCalled()
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'bank-detail', selectedBankId: bank.id, editingQuestion: null } })
  })

  it('edits an existing question without pretending its type can change', async () => {
    const dispatch = vi.fn()
    const refresh = vi.fn().mockResolvedValue(undefined)
    const updateQuestion = vi.fn().mockResolvedValue({})
    const question = {
      id: 'question-1',
      bankId: bank.id,
      bankName: bank.name,
      prompt: 'Original prompt',
      instruction: 'Choose one answer.',
      type: 'Single choice',
      image: false,
      status: 'Ready',
      version: 1,
      updated: 'v1',
      options: [
        { text: 'Option A', is_correct: true },
        { text: 'Option B', is_correct: false },
      ],
    }

    render(
      <CreateQuestionPage
        state={{ staff: { section: 'edit-question', selectedBankId: bank.id, selectedQuestionId: question.id } }}
        dispatch={dispatch}
        teacherData={{ banks: [bank], questions: [question], refresh }}
        gateway={{ media: { uploadQuestionImage: vi.fn() }, questions: { updateQuestion } }}
      />,
    )

    expect(screen.getByText(/question type is fixed after creation/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/question instruction/i)).toHaveValue('Choose one answer.')
    fireEvent.change(screen.getByLabelText(/question prompt/i), { target: { value: 'Updated prompt' } })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(updateQuestion).toHaveBeenCalledWith(question.id, {
      prompt: 'Updated prompt',
      instruction: 'Choose one answer.',
      options: [
        { text: 'Option A', is_correct: true },
        { text: 'Option B', is_correct: false },
      ],
    }))
    expect(refresh).toHaveBeenCalled()
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'questions', selectedQuestionId: null, editingQuestion: null } })
  })
})
