import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OverviewPage } from '../src/features/teacher/OverviewPage'

describe('Teacher overview', () => {
  it('renders real academic and exam data in the reference dashboard layout', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-16T19:00:00'))
    const dispatch = vi.fn()
    const { container } = render(
      <OverviewPage
        state={{
          branding: { school_name: 'Debright College', logo_revision: 'rev-1', logo_path: 'branding/logo.png', is_enabled: true },
          installation: { status: { tenant_name: 'Debright College' } },
          session: { actor: { display_name: 'Taiwo A.', role: 'teacher' } },
        }}
        dispatch={dispatch}
        teacherData={{
          banks: [{ id: 'bank-1', name: 'Mathematics', count: 12 }],
          questions: [],
          subjects: [{ id: 'subject-1', name: 'Mathematics' }, { id: 'subject-2', name: 'Physics' }],
          assignments: [{ curriculumSubjectId: 'subject-1', subjectName: 'Mathematics', className: 'SS2 A' }],
          exams: [
            { id: 'exam-1', title: 'Mathematics CA 1', subjectName: 'Mathematics', questionCount: 30, selectionMode: 'manual', status: 'draft' },
            { id: 'exam-2', title: 'Physics Test', subjectName: 'Physics', questionCount: 20, selectionMode: 'random', status: 'submitted' },
          ],
          session: { id: 'session-1', name: '2026/2027 Academic Session' },
          term: { id: 'term-1', name: 'First Term' },
          loading: false,
          error: '',
          warning: '',
        }}
      />,
    )

    expect(screen.getByRole('heading', { name: /teacher's dashboard/i })).toBeInTheDocument()
    expect(screen.getByText('Debright College')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /debright college logo/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /good evening, taiwo/i })).toBeInTheDocument()
    expect(container.querySelector('.teacher-overview-time-icon')).toHaveAttribute('data-time-icon', 'moon')
    expect(screen.queryByText(/better teachers build/i)).not.toBeInTheDocument()
    expect(screen.getByText(/2026\/2027 academic session/i)).toBeInTheDocument()
    expect(screen.getByText(/first term/i)).toBeInTheDocument()
    expect(container.querySelectorAll('.teacher-overview-stat')).toHaveLength(4)
    expect(screen.getByText('Mathematics CA 1')).toBeInTheDocument()
    expect(screen.getByText('SS2 A')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: /teacher quick actions/i })).not.toBeInTheDocument()
    const quickActions = screen.getByRole('button', { name: /^quick actions$/i })
    fireEvent.click(quickActions)
    expect(screen.getByRole('menu', { name: /teacher quick actions/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /create question/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /create exam/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /question banks/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /view all exams/i })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('menuitem', { name: /create exam/i }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'create-exam' } })
    expect(screen.queryByRole('menu', { name: /teacher quick actions/i })).not.toBeInTheDocument()

    fireEvent.click(quickActions)
    fireEvent.click(screen.getByRole('menuitem', { name: /question banks/i }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'question-banks' } })

    fireEvent.click(screen.getByRole('button', { name: /continue/i }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'exams', selectedExamId: 'exam-1' } })
    vi.useRealTimers()
  })
})
