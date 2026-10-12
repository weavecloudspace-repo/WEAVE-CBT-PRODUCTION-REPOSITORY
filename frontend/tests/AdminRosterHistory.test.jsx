import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ToastHost } from '../src/shared/ui/ToastHost'
import { AdminRosterDetailPage } from '../src/features/admin/pages/AdminRostersPage'
import { AdminCurrentRostersPage, AdminRosterHistoryPage } from '../src/features/admin/pages/AdminRosterViews'

function makeSubject() {
  return {
    id: 'jss1-english',
    academicLevelId: 'jss1',
    academicLevelName: 'JSS1',
    academicLevelCategory: 'junior_secondary',
    academicLevelPosition: 1,
    name: 'English',
    code: 'ENG',
  }
}

function makeExam(overrides = {}) {
  return {
    id: 'exam-r1',
    title: 'JSS1 ENGLISH EXAM',
    sessionId: 'session-1',
    termId: 'term-1',
    academicLevelId: 'jss1',
    academicLevelName: 'JSS1',
    subjectName: 'English',
    subjectCode: 'ENG',
    curriculumSubjectId: 'jss1-english',
    assessmentComponentId: 'exam-component',
    assessmentName: 'Exam',
    status: 'sealed',
    statusLabel: 'Sealed',
    rosterStatus: 'ready',
    rosterVersion: 1,
    rosterCandidateCount: 1,
    rosterPreparedAt: '2026-09-28T16:00:00Z',
    rosterError: '',
    revisionNumber: 1,
    revisionOfExamId: null,
    scheduledStartAt: '2026-09-28T17:00:00Z',
    createdAt: '2026-09-28T15:00:00Z',
    updatedAt: '2026-09-28T16:00:00Z',
    ...overrides,
  }
}

function makeAdminData(exams) {
  return {
    exams,
    subjects: [makeSubject()],
    loading: false,
    error: '',
    warning: '',
    refreshExams: vi.fn().mockResolvedValue(undefined),
  }
}

function threeRevisionLineage() {
  const revision1 = makeExam({
    id: 'english-r1',
    revisionNumber: 1,
    rosterVersion: 2,
    rosterCandidateCount: 2,
  })
  const revision2 = makeExam({
    id: 'english-r2',
    revisionNumber: 2,
    revisionOfExamId: revision1.id,
    rosterVersion: 3,
    rosterCandidateCount: 2,
    createdAt: '2026-09-28T16:10:00Z',
    updatedAt: '2026-09-28T16:20:00Z',
  })
  const revision3 = makeExam({
    id: 'english-r3',
    status: 'suspended',
    statusLabel: 'Suspended',
    revisionNumber: 3,
    revisionOfExamId: revision2.id,
    rosterVersion: 1,
    rosterCandidateCount: 1,
    createdAt: '2026-09-28T16:30:00Z',
    updatedAt: '2026-09-28T17:10:00Z',
  })
  return [revision1, revision2, revision3]
}

it('keeps the main roster page operational-only and links to roster history', () => {
  const onNavigate = vi.fn()
  const [revision1, revision2, revision3] = threeRevisionLineage()

  render(
    <AdminCurrentRostersPage
      adminData={makeAdminData([revision1, revision2, revision3])}
      onNavigate={onNavigate}
    />,
  )

  const current = screen.getByRole('region', { name: /current rosters/i })
  expect(within(current).getByRole('button', { name: /open roster for jss1 english exam revision 3/i })).toBeInTheDocument()
  expect(within(current).queryByRole('button', { name: /revision 1/i })).not.toBeInTheDocument()
  expect(within(current).queryByRole('button', { name: /revision 2/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: /^roster history$/i })).not.toBeInTheDocument()

  const historyButton = screen.getByRole('button', { name: /view roster history/i })
  expect(historyButton).toHaveTextContent(/^View roster history$/)
  fireEvent.click(historyButton)
  expect(onNavigate).toHaveBeenCalledWith('roster-history')
})

it('groups previous revisions together on the dedicated history page', () => {
  const [revision1, revision2, revision3] = threeRevisionLineage()

  render(
    <AdminRosterHistoryPage
      adminData={makeAdminData([revision1, revision2, revision3])}
      onNavigate={vi.fn()}
    />,
  )

  expect(screen.getByRole('heading', { name: /^roster history$/i })).toBeInTheDocument()
  const history = screen.getByRole('region', { name: /historical rosters/i })
  expect(within(history).getByText('2 historical rosters')).toBeInTheDocument()
  expect(within(history).getByRole('button', { name: /open historical roster for jss1 english exam revision 2/i })).toBeInTheDocument()
  expect(within(history).getByRole('button', { name: /open historical roster for jss1 english exam revision 1/i })).toBeInTheDocument()
  expect(within(history).queryByRole('button', { name: /revision 3/i })).not.toBeInTheDocument()
})

it('filters historical rosters by lifecycle kind', () => {
  const closed = makeExam({
    id: 'closed-exam',
    title: 'JSS1 ENGLISH TEST',
    assessmentComponentId: 'test-component',
    assessmentName: 'Test',
    status: 'closed',
    statusLabel: 'Closed',
  })
  const cancelled = makeExam({
    id: 'cancelled-exam',
    title: 'JSS1 ENGLISH PRACTICE',
    assessmentComponentId: 'practice-component',
    assessmentName: 'Practice',
    status: 'cancelled',
    statusLabel: 'Cancelled',
  })

  render(
    <AdminRosterHistoryPage
      adminData={makeAdminData([closed, cancelled])}
      onNavigate={vi.fn()}
    />,
  )

  expect(screen.getByRole('button', { name: /open historical roster for jss1 english test revision 1/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /open historical roster for jss1 english practice revision 1/i })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('combobox', { name: /roster history type filter/i }))
  fireEvent.click(screen.getByRole('option', { name: /^Closed exams$/i }))

  expect(screen.getByRole('button', { name: /open historical roster for jss1 english test revision 1/i })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /open historical roster for jss1 english practice revision 1/i })).not.toBeInTheDocument()
})

it('opens the exact historical revision rather than the current exam revision', () => {
  const onNavigate = vi.fn()
  const revision1 = makeExam({ id: 'english-r1', revisionNumber: 1 })
  const revision2 = makeExam({
    id: 'english-r2',
    revisionNumber: 2,
    revisionOfExamId: revision1.id,
    status: 'active',
    statusLabel: 'Active',
  })

  render(
    <AdminRosterHistoryPage
      adminData={makeAdminData([revision1, revision2])}
      onNavigate={onNavigate}
    />,
  )

  fireEvent.click(
    screen.getByRole('button', {
      name: /open historical roster for jss1 english exam revision 1/i,
    }),
  )

  expect(onNavigate).toHaveBeenCalledWith('roster-detail', {
    selectedExamId: 'english-r1',
  })
})

it('keeps historical candidate lists accessible while making the snapshot read-only', async () => {
  const revision1 = makeExam({
    id: 'english-r1',
    revisionNumber: 1,
    rosterVersion: 2,
    rosterCandidateCount: 2,
  })
  const revision2 = makeExam({
    id: 'english-r2',
    revisionNumber: 2,
    revisionOfExamId: revision1.id,
    status: 'suspended',
    statusLabel: 'Suspended',
  })
  const listExamRoster = vi.fn().mockResolvedValue({
    exam_id: revision1.id,
    roster_status: 'ready',
    roster_version: 2,
    roster_candidate_count: 2,
    offset: 0,
    limit: 50,
    total: 1,
    classes: [{ id: 'class-a', display_name: 'JSS1 A' }],
    candidates: [{
      id: 'candidate-1',
      exam_id: revision1.id,
      enrollment_id: 'enrollment-1',
      student_id: 'student-1',
      class_id: 'class-a',
      class_name: 'JSS1 A',
      admission_number: 'JSS1/001',
      display_name: 'Ada Okafor',
      status: 'eligible',
      status_reason: null,
      roster_version: 2,
    }],
  })
  const gateway = {
    candidates: {
      listExamRoster,
      retryFailedRoster: vi.fn(),
    },
  }

  render(
    <>
      <ToastHost />
      <AdminRosterDetailPage
        state={{ staff: { selectedExamId: revision1.id } }}
        adminData={makeAdminData([revision1, revision2])}
        gateway={gateway}
        onNavigate={vi.fn()}
      />
    </>,
  )

  await waitFor(() => expect(listExamRoster).toHaveBeenCalledWith('english-r1', {
    offset: 0,
    limit: 50,
  }))

  expect(await screen.findByText('Ada Okafor')).toBeInTheDocument()
  expect(screen.getByText('JSS1/001')).toBeInTheDocument()
  expect(screen.getByText('Read only')).toBeInTheDocument()
  expect(screen.getByText(/candidate records remain fully available below, but this roster is read-only/i)).toBeInTheDocument()
  expect(screen.getAllByText('Revision 1').length).toBeGreaterThan(0)
  expect(screen.getByText('v2')).toBeInTheDocument()
})
