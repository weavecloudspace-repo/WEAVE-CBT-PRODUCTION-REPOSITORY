import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AdminExamsPage } from '../src/features/admin/pages/AdminExamsPage'

function makeExam(overrides = {}) {
  return {
    id: 'exam-1',
    title: 'English CA 1',
    academicLevelName: 'JSS1',
    subjectName: 'English Language',
    assessmentName: 'CA 1',
    curriculumSubjectId: 'subject-1',
    assessmentComponentId: 'component-1',
    questionCount: 20,
    durationMinutes: 45,
    selectionMode: 'random',
    status: 'submitted',
    statusLabel: 'Submitted',
    rosterStatus: 'pending',
    authoringVersion: 4,
    revisionNumber: 1,
    scheduledStartAt: null,
    updatedAt: '2026-09-17T09:00:00Z',
    ...overrides,
  }
}

function makeAdminData(exams) {
  return {
    exams,
    subjects: [{ id: 'subject-1', name: 'English Language', code: 'ENG' }],
    assessmentComponents: [{ id: 'component-1', name: 'CA 1', maximumScore: 10 }],
    loading: false,
    error: '',
    warning: '',
    refresh: vi.fn().mockResolvedValue(undefined),
  }
}

function makeGateway() {
  return {
    exams: {
      submitExam: vi.fn().mockResolvedValue({}),
      deleteDraftExam: vi.fn().mockResolvedValue(null),
      returnExamToDraft: vi.fn().mockResolvedValue({}),
      sealExam: vi.fn().mockResolvedValue({}),
      createRevision: vi.fn().mockResolvedValue({}),
      activateExam: vi.fn().mockResolvedValue({}),
      suspendExam: vi.fn().mockResolvedValue({}),
      resumeExam: vi.fn().mockResolvedValue({}),
      closeExam: vi.fn().mockResolvedValue({}),
      cancelExam: vi.fn().mockResolvedValue({}),
    },
  }
}

describe('Admin examination preparation workspace', () => {
  it('exposes submitted-paper review actions and executes sealing through the real gateway', async () => {
    const data = makeAdminData([makeExam()])
    const gateway = makeGateway()

    render(<AdminExamsPage adminData={data} gateway={gateway} onNavigate={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /paper actions for english ca 1/i }))
    expect(screen.getByRole('button', { name: /return to draft/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /seal examination/i }))

    expect(screen.getByRole('alertdialog')).toHaveTextContent(/seal this examination/i)
    fireEvent.click(screen.getByRole('button', { name: /^seal examination$/i }))

    await waitFor(() => expect(gateway.exams.sealExam).toHaveBeenCalledWith('exam-1'))
    expect(data.refresh).toHaveBeenCalled()
  })

  it('hands sealed execution control to Exam Operations instead of exposing activation on the paper page', () => {
    const onNavigate = vi.fn()
    const data = makeAdminData([
      makeExam({ id: 'exam-2', title: 'English Final', status: 'sealed', statusLabel: 'Sealed', rosterStatus: 'ready' }),
    ])

    render(<AdminExamsPage adminData={data} gateway={makeGateway()} onNavigate={onNavigate} />)

    fireEvent.click(screen.getByRole('button', { name: /paper actions for english final/i }))

    expect(screen.queryByRole('button', { name: /activate examination/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /suspend examination/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /close examination/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /cancel sitting/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create revision/i })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: /open exam operations/i }))
    expect(onNavigate).toHaveBeenCalledWith('operation-detail', { selectedExamId: 'exam-2' })
  })

  it('keeps live examinations read-only in preparation and routes administrators to operations', () => {
    const onNavigate = vi.fn()
    const data = makeAdminData([
      makeExam({ id: 'exam-3', title: 'English Mock', status: 'active', statusLabel: 'Active', rosterStatus: 'ready' }),
    ])

    render(<AdminExamsPage adminData={data} gateway={makeGateway()} onNavigate={onNavigate} />)

    fireEvent.click(screen.getByRole('button', { name: /paper actions for english mock/i }))
    expect(screen.queryByRole('button', { name: /suspend examination/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /close examination/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /open exam operations/i }))
    expect(onNavigate).toHaveBeenCalledWith('operation-detail', { selectedExamId: 'exam-3' })
  })
})


describe('Authoring revision eligibility', () => {
  it.each(['pending_review', 'approved', 'voided', null])('uses the backend review decision %s', async (disposition) => {
    const gateway = makeGateway()
    gateway.results = { listResultReviewSets: vi.fn().mockResolvedValue({ reviews: [{ exam_id: 'exam-1', result_disposition: disposition }] }) }
    gateway.exams.createRevision.mockResolvedValue({ id: 'exam-2' })
    const navigate = vi.fn()
    render(<AdminExamsPage adminData={makeAdminData([makeExam({ status: 'closed', statusLabel: 'Closed' })])} gateway={gateway} onNavigate={navigate} />)
    fireEvent.click(screen.getByRole('button', { name: /paper actions/i }))
    await waitFor(() => expect(gateway.results.listResultReviewSets).toHaveBeenCalled())
    if (disposition === 'voided') {
      fireEvent.click(await screen.findByRole('button', { name: /reconduct examination/i }))
      expect(gateway.exams.createRevision).not.toHaveBeenCalled()
      fireEvent.click(screen.getByRole('button', { name: /^create revision$/i }))
      await waitFor(() => expect(navigate).toHaveBeenCalledWith('create-exam', { selectedExamId: 'exam-2' }))
      expect(gateway.exams.createRevision).toHaveBeenCalledWith('exam-1')
    } else expect(screen.queryByRole('button', { name: /create revision/i })).not.toBeInTheDocument()
  })

  it('groups before filtering and preserves only the latest revision card', () => {
    render(<AdminExamsPage adminData={makeAdminData([
      makeExam({ id: 'old', title: 'Old title', status: 'sealed' }),
      makeExam({ id: 'new', title: 'Renamed paper', status: 'draft', revisionNumber: 2 }),
    ])} gateway={makeGateway()} onNavigate={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Open Old title' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Renamed paper' })).toBeInTheDocument()
    expect(screen.getByText('Revision 2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('combobox', { name: 'Lifecycle filter' }))
    fireEvent.click(screen.getByRole('option', { name: /^Sealed/ }))
    expect(screen.queryByRole('button', { name: 'Open Old title' })).not.toBeInTheDocument()
  })

  it('fails closed when review data cannot load', async () => {
    const gateway = makeGateway()
    gateway.results = { listResultReviewSets: vi.fn().mockRejectedValue(new Error('offline')) }
    render(<AdminExamsPage adminData={makeAdminData([makeExam({ status: 'closed' })])} gateway={gateway} onNavigate={vi.fn()} />)
    await screen.findByText(/Result decisions could not be loaded/)
    fireEvent.click(screen.getByRole('button', { name: /paper actions/i }))
    expect(screen.queryByRole('button', { name: /create revision/i })).not.toBeInTheDocument()
  })
})

it('offers every backend lifecycle in one compact filter', () => {
  render(<AdminExamsPage adminData={makeAdminData([makeExam()])} gateway={makeGateway()} onNavigate={vi.fn()} />)
  expect(screen.queryByRole('navigation', { name: 'Exam preparation filters' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('combobox', { name: 'Lifecycle filter' }))
  for (const status of ['All statuses', 'Draft', 'Submitted', 'Sealed', 'Active', 'Suspended', 'Closing', 'Closed', 'Cancelling', 'Cancelled']) {
    expect(screen.getByRole('option', { name: new RegExp(`^${status}`) })).toBeInTheDocument()
  }
})

it('scopes subjects by level and resets the subject when the level changes', () => {
  const data = makeAdminData([
    makeExam({ id: 'jss1', title: 'JSS1 English', academicLevelId: 'level-1' }),
    makeExam({ id: 'jss2', title: 'JSS2 English', academicLevelId: 'level-2', curriculumSubjectId: 'subject-2' }),
  ])
  data.subjects = [
    { id: 'subject-1', name: 'English', academicLevelId: 'level-1', academicLevelName: 'JSS1', academicLevelPosition: 1 },
    { id: 'subject-2', name: 'English', academicLevelId: 'level-2', academicLevelName: 'JSS2', academicLevelPosition: 2 },
  ]
  render(<AdminExamsPage adminData={data} gateway={makeGateway()} onNavigate={vi.fn()} />)
  fireEvent.click(screen.getByRole('combobox', { name: 'Academic level filter' }))
  fireEvent.click(screen.getByRole('option', { name: 'JSS1' }))
  expect(screen.getByRole('button', { name: 'Open JSS1 English' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Open JSS2 English' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('combobox', { name: 'Exam subject filter' }))
  expect(screen.getAllByRole('option')).toHaveLength(2)
  fireEvent.click(screen.getByRole('option', { name: 'English' }))
  fireEvent.click(screen.getByRole('combobox', { name: 'Academic level filter' }))
  fireEvent.click(screen.getByRole('option', { name: 'JSS2' }))
  expect(screen.getByRole('combobox', { name: 'Exam subject filter' })).toHaveTextContent('All subjects')
  expect(screen.getByRole('button', { name: 'Open JSS2 English' })).toBeInTheDocument()
})

it.each(['submitted', 'sealed', 'active', 'suspended', 'closing', 'cancelling', 'closed', 'cancelled'])('hides the card edit action for %s', (status) => {
  const gateway = makeGateway()
  gateway.results = { listResultReviewSets: vi.fn().mockResolvedValue({ reviews: [] }) }
  render(<AdminExamsPage adminData={makeAdminData([makeExam({ status })])} gateway={gateway} onNavigate={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'Edit English CA 1' })).not.toBeInTheDocument()
})
