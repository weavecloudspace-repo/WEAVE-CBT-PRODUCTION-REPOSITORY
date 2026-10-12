import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { AdminWorkspace } from '../src/features/admin/AdminWorkspace'
import { useAdminData } from '../src/features/admin/useAdminData'

vi.mock('../src/features/admin/useAdminData', () => ({ useAdminData: vi.fn() }))

it('preserves the actual exam form and picker search while visiting a question preview', async () => {
  const question = { id: 'q1', bank_id: 'b1', prompt: 'Which answer?', author_name: 'Admin', question_type: 'single_choice', is_active: true, options: [] }
  const data = {
    loading: false, banks: [{ id: 'b1', name: 'English', status: 'Ready', curriculumSubjectId: 's1', count: 1 }],
    exams: [{ id: 'e1', title: 'Original title', status: 'draft', curriculumSubjectId: 's1', questionBankId: 'b1', selectionMode: 'manual', questionCount: 1, assessmentSchemeId: 'scheme', assessmentComponentId: 'component', authoringVersion: 1 }],
    subjects: [{ id: 's1', name: 'English', academicLevelId: 'l1', academicLevelName: 'JSS1' }],
    assessmentSchemes: [{ id: 'scheme', name: 'Scheme' }], assessmentComponents: [{ id: 'component', schemeId: 'scheme', name: 'Exam' }],
    assignments: [], session: { id: 'session', name: 'Session' }, term: { id: 'term', name: 'Term' }, refresh: vi.fn(),
  }
  useAdminData.mockReturnValue(data)
  const gateway = {
    questions: { listQuestionsForBank: vi.fn().mockResolvedValue([question]), getQuestion: vi.fn().mockResolvedValue(question) },
    exams: { listManualQuestions: vi.fn().mockResolvedValue([{ question_id: 'q1', added_by_actor_id: 'admin' }]), getExam: vi.fn().mockResolvedValue({ authoring_version: 1 }), listLeadCandidates: vi.fn().mockResolvedValue([]) },
  }
  function Workspace() {
    const [state, setState] = useState({ staff: { section: 'create-exam', selectedExamId: 'e1' }, session: { role: 'admin', actor: { id: 'admin', role: 'admin' } } })
    return <AdminWorkspace state={state} dispatch={(action) => setState((previous) => ({ ...previous, staff: { ...previous.staff, ...action.patch } }))} gateway={gateway} signOut={vi.fn()} />
  }
  render(<Workspace />)
  await screen.findByRole('button', { name: 'Preview question: Which answer?' })
  fireEvent.change(screen.getByLabelText('Exam title'), { target: { value: 'Unsaved title' } })
  fireEvent.change(screen.getByLabelText('Search bank questions'), { target: { value: 'Which' } })
  fireEvent.click(screen.getByRole('button', { name: 'Preview question: Which answer?' }))
  expect(await screen.findByRole('heading', { name: 'Question preview' })).toBeInTheDocument()
  expect(screen.queryByRole('textbox', { name: 'Exam title' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Back to exam form' }))
  expect(screen.getByRole('button', { name: 'Preview question: Which answer?' })).toHaveFocus()
  expect(screen.getByLabelText('Exam title')).toHaveValue('Unsaved title')
  expect(screen.getByLabelText('Search bank questions')).toHaveValue('Which')
  expect(screen.getByRole('button', { name: 'Remove question from exam: Which answer?' })).toBeInTheDocument()
  expect(gateway.questions.listQuestionsForBank).toHaveBeenCalledTimes(1)
})
