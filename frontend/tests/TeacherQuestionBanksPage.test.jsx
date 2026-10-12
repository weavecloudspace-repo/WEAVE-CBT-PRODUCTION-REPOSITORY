import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BankDetailPage, QuestionBanksPage } from '../src/features/teacher/QuestionBanksPage'

describe('Teacher question bank detail', () => {
  const teacherData = {
    banks: [{ id: 'bank-1', name: 'JSS1 English', count: 2 }],
    questions: [
      { id: 'q-1', bankId: 'bank-1', prompt: 'Choose the correct noun.', type: 'Single choice', status: 'Ready', updated: 'v2', image: false },
      { id: 'q-2', bankId: 'bank-1', prompt: 'Select every verb.', type: 'Multiple choice', status: 'Archived', updated: 'v1', image: true },
    ],
  }

  it('lists only the selected bank questions without a create or refresh action', () => {
    render(
      <BankDetailPage
        state={{ staff: { selectedBankId: 'bank-1' } }}
        dispatch={vi.fn()}
        teacherData={teacherData}
      />,
    )

    expect(screen.getByRole('heading', { name: 'JSS1 English' })).toBeInTheDocument()
    expect(screen.getByText('2 questions in this bank')).toBeInTheDocument()
    const list = screen.getByRole('region', { name: 'Questions in this bank' })
    expect(within(list).getByText('Choose the correct noun.')).toBeInTheDocument()
    expect(within(list).getByText('Select every verb.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /add question/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /refresh/i })).not.toBeInTheDocument()
  })

  it('returns to the bank list from the single navigation action', () => {
    const dispatch = vi.fn()
    render(
      <BankDetailPage
        state={{ staff: { selectedBankId: 'bank-1' } }}
        dispatch={dispatch}
        teacherData={teacherData}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /back to question banks/i }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'question-banks' } })
  })
})

describe('Teacher question bank list', () => {
  it('keeps bank guidance in a compact popover and refreshes from the card', () => {
    const refresh = vi.fn()
    render(
      <QuestionBanksPage
        dispatch={vi.fn()}
        teacherData={{
          banks: [{ id: 'bank-1', name: 'JSS1 English', count: 2, status: 'Ready' }],
          questions: [],
          loading: false,
          error: '',
          refresh,
        }}
      />,
    )

    expect(screen.queryByText(/you only see banks/i)).not.toBeInTheDocument()
    const helpButton = screen.getByRole('button', { name: /question bank help/i })
    fireEvent.click(helpButton)

    const helpCard = screen.getByRole('dialog', { name: /question bank help/i })
    expect(within(helpCard).getByText(/you only see banks/i)).toBeInTheDocument()
    fireEvent.click(within(helpCard).getByRole('button', { name: /refresh banks/i }))

    expect(refresh).toHaveBeenCalledOnce()
    expect(screen.queryByRole('dialog', { name: /question bank help/i })).not.toBeInTheDocument()
  })
})
