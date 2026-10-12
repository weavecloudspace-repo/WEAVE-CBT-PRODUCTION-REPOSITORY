import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AdminQuestionBanksPage } from '../src/features/admin/pages/AdminQuestionBanks'

function adminData() {
  return {
    banks: [
      {
        id: 'bank-1',
        curriculumSubjectId: 'subject-1',
        academicLevelId: 'level-jss1',
        academicLevelName: 'JSS1',
        subjectName: 'English Language',
        subjectCode: 'ENG',
        name: 'JSS1 English',
        description: 'First year English questions',
        status: 'Ready',
        count: 4,
        canDelete: false,
        activeQuestionCount: 3,
      },
      {
        id: 'bank-2',
        curriculumSubjectId: 'subject-2',
        academicLevelId: 'level-jss1',
        academicLevelName: 'JSS1',
        subjectName: 'Mathematics',
        subjectCode: 'MTH',
        name: 'JSS1 Mathematics Archive',
        description: null,
        status: 'Archived',
        count: 0,
        canDelete: true,
        activeQuestionCount: 0,
      },
    ],
    subjects: [
      {
        id: 'subject-1',
        academicLevelId: 'level-jss1',
        academicLevelName: 'JSS1',
        academicLevelCategory: 'junior_secondary',
        academicLevelPosition: 1,
        name: 'English Language',
        code: 'ENG',
      },
      {
        id: 'subject-2',
        academicLevelId: 'level-jss1',
        academicLevelName: 'JSS1',
        academicLevelCategory: 'junior_secondary',
        academicLevelPosition: 1,
        name: 'Mathematics',
        code: 'MTH',
      },
      {
        id: 'subject-3',
        academicLevelId: 'level-jss2',
        academicLevelName: 'JSS2',
        academicLevelCategory: 'junior_secondary',
        academicLevelPosition: 2,
        name: 'Basic Science',
        code: 'BSC',
      },
    ],
    loading: false,
    error: '',
    warning: '',
    refresh: vi.fn().mockResolvedValue(undefined),
  }
}

describe('Admin question bank workspace', () => {
  it.each([false, undefined])('hides delete for an empty bank when eligibility is %s', (canDelete) => {
    const data = adminData()
    data.banks[1].canDelete = canDelete
    render(<AdminQuestionBanksPage adminData={data} gateway={{ questions: {} }} onNavigate={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /manage jss1 mathematics archive/i }))
    expect(screen.queryByRole('menuitem', { name: /delete empty bank/i })).not.toBeInTheDocument()
  })

  it('shows all school banks and exposes admin bank lifecycle actions', async () => {
    const data = adminData()
    const gateway = {
      questions: {
        archiveQuestionBank: vi.fn().mockResolvedValue({}),
        reactivateQuestionBank: vi.fn().mockResolvedValue({}),
        deleteEmptyQuestionBank: vi.fn().mockResolvedValue(null),
        createQuestionBank: vi.fn(),
        updateQuestionBank: vi.fn(),
      },
    }

    render(
      <AdminQuestionBanksPage
        adminData={data}
        gateway={gateway}
        onNavigate={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: /question banks/i })).toBeInTheDocument()
    expect(screen.getByText('JSS1 English')).toBeInTheDocument()
    expect(screen.getByText('JSS1 Mathematics Archive')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create bank/i })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /manage jss1 english/i }))
    expect(screen.queryByRole('menuitem', { name: /delete empty bank/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: /archive bank/i }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/archive this question bank/i)
    fireEvent.click(screen.getByRole('button', { name: /^archive bank$/i }))

    await waitFor(() => expect(gateway.questions.archiveQuestionBank).toHaveBeenCalledWith('bank-1'))
    expect(data.refresh).toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /manage jss1 mathematics archive/i }))
    expect(screen.getByRole('menuitem', { name: /reactivate bank/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /delete empty bank/i })).toBeEnabled()
  })

  it('filters curriculum subjects by academic level before creating a bank', async () => {
    const data = adminData()
    const gateway = {
      questions: {
        createQuestionBank: vi.fn().mockResolvedValue({ id: 'bank-new' }),
        updateQuestionBank: vi.fn(),
      },
    }

    render(
      <AdminQuestionBanksPage
        adminData={data}
        gateway={gateway}
        onNavigate={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /create bank/i }))

    expect(screen.getByRole('heading', { name: /create question bank/i })).toBeInTheDocument()
    const levelSelect = screen.getByRole('combobox', { name: /academic level/i })
    const subjectSelect = screen.getByRole('combobox', { name: /^subject$/i })
    expect(levelSelect).toHaveTextContent('JSS1')
    expect(subjectSelect).toHaveTextContent('English Language')

    fireEvent.click(levelSelect)
    fireEvent.click(screen.getByRole('option', { name: /JSS2/i }))

    expect(screen.getByRole('combobox', { name: /^subject$/i })).toHaveTextContent('Basic Science')
    fireEvent.click(screen.getByRole('combobox', { name: /^subject$/i }))
    expect(screen.getByRole('option', { name: /Basic Science/i })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /English Language/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('option', { name: /Basic Science/i }))

    fireEvent.change(screen.getByPlaceholderText(/jss2 basic science/i), { target: { value: 'JSS2 Basic Science Bank' } })
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^create bank$/i }))

    await waitFor(() => expect(gateway.questions.createQuestionBank).toHaveBeenCalledWith(
      'subject-3',
      { name: 'JSS2 Basic Science Bank', description: null },
    ))
  })
})
