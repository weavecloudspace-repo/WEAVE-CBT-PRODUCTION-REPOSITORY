import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AdminWorkspace } from '../src/features/admin/AdminWorkspace'

function makeState() {
  return {
    staff: {
      section: 'dashboard',
      selectedExamId: null,
      selectedQuestionId: null,
      selectedBankId: null,
    },
    session: {
      actor: { display_name: 'Administrator' },
    },
    branding: {},
    installation: {
      status: {
        tenant_name: 'Demo School',
        server_name: 'CBT Server',
      },
    },
  }
}

function makeGateway() {
  return {
    questions: {
      listAdminQuestionBanks: vi.fn().mockResolvedValue([]),
    },
  }
}

describe('Admin grouped sidebar navigation', () => {
  it('keeps related question and examination workspaces inside expandable groups', async () => {
    render(
      <AdminWorkspace
        state={makeState()}
        dispatch={vi.fn()}
        signOut={vi.fn()}
        gateway={makeGateway()}
      />,
    )

    expect(screen.getByRole('navigation', { name: /administrator navigation/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Reports$/i })).not.toBeInTheDocument()
    const questionsGroup = screen.getByRole('button', { name: /^Questions$/i })
    const examinationsGroup = screen.getByRole('button', { name: /^Examinations$/i })

    expect(questionsGroup).toHaveAttribute('aria-expanded', 'false')
    expect(examinationsGroup).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('button', { name: /^Question Banks$/i })).not.toBeInTheDocument()

    fireEvent.click(questionsGroup)

    expect(questionsGroup).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: /^Question Banks$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Question Library$/i })).toBeInTheDocument()

    fireEvent.click(examinationsGroup)

    expect(examinationsGroup).toHaveAttribute('aria-expanded', 'true')
    expect(questionsGroup).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('button', { name: /^Question Banks$/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Exams$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Roster$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Exam Operations$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Invigilators$/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Results$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Makeups$/i })).toBeInTheDocument()

    await waitFor(() => expect(screen.getByRole('heading', { name: /administrator dashboard/i })).toBeInTheDocument())
  })

  it('routes an examination child through the existing workspace navigation contract', () => {
    const dispatch = vi.fn()
    render(
      <AdminWorkspace
        state={makeState()}
        dispatch={dispatch}
        signOut={vi.fn()}
        gateway={makeGateway()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /^Examinations$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^Roster$/i }))

    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'roster', timetableLevelId: null } })
    fireEvent.click(screen.getByRole('button', { name: /^Results$/i }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'results', timetableLevelId: null } })
    fireEvent.click(screen.getByRole('button', { name: /^Makeups$/i }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'makeups', timetableLevelId: null } })
    expect(screen.getByRole('button', { name: /^Examinations$/i })).toHaveAttribute('aria-expanded', 'true')
  })
})
