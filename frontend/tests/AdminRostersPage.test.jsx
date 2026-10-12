import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { AdminRosterDetailPage } from '../src/features/admin/pages/AdminRostersPage'
import { AdminCurrentRostersPage } from '../src/features/admin/pages/AdminRosterViews'

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
})

function makeSubject(overrides = {}) {
  return {
    id: 'jss1-math',
    academicLevelId: 'jss1',
    academicLevelName: 'JSS1',
    academicLevelCategory: 'junior_secondary',
    academicLevelPosition: 1,
    name: 'Mathematics',
    code: 'MTH',
    ...overrides,
  }
}

function makeExam(overrides = {}) {
  return {
    id: 'exam-1',
    title: 'Mathematics CA 1',
    sessionId: 'session-1',
    termId: 'term-1',
    academicLevelId: 'jss1',
    academicLevelName: 'JSS1',
    subjectName: 'Mathematics',
    subjectCode: 'MTH',
    curriculumSubjectId: 'jss1-math',
    assessmentComponentId: 'ca1-component',
    assessmentName: 'CA 1',
    status: 'sealed',
    statusLabel: 'Sealed',
    rosterStatus: 'ready',
    rosterVersion: 2,
    rosterCandidateCount: 126,
    rosterPreparedAt: '2026-09-18T08:00:00Z',
    rosterError: '',
    revisionNumber: 1,
    revisionOfExamId: null,
    scheduledStartAt: '2026-09-19T09:00:00Z',
    createdAt: '2026-09-18T08:00:00Z',
    updatedAt: '2026-09-18T08:00:00Z',
    ...overrides,
  }
}

function makeAdminData(exams) {
  return {
    exams,
    subjects: [
      makeSubject(),
      makeSubject({ id: 'jss2-math', academicLevelId: 'jss2', academicLevelName: 'JSS2', academicLevelPosition: 2 }),
      makeSubject({ id: 'jss2-science', academicLevelId: 'jss2', academicLevelName: 'JSS2', academicLevelPosition: 2, name: 'Basic Science', code: 'BSC' }),
    ],
    loading: false,
    error: '',
    warning: '',
    refreshExams: vi.fn().mockResolvedValue(undefined),
  }
}

function candidate(overrides = {}) {
  return {
    id: 'candidate-1',
    exam_id: 'exam-1',
    enrollment_id: 'enrollment-1',
    student_id: 'student-1',
    class_id: 'class-a',
    class_name: 'JSS1 A',
    admission_number: 'JSS1/001',
    display_name: 'Ada Okafor',
    status: 'eligible',
    status_reason: null,
    roster_version: 2,
    attempt: null,
    late_start_authorized: false,
    late_start_required: false,
    ...overrides,
  }
}

function rosterPayload(exam, candidates, overrides = {}) {
  return {
    exam_id: exam.id,
    roster_status: 'ready',
    roster_version: 2,
    roster_candidate_count: 126,
    eligible_not_started_count: candidates.filter((item) => item.status === 'eligible' && !item.attempt).length,
    in_progress_count: candidates.filter((item) => item.attempt?.status === 'in_progress').length,
    interrupted_count: candidates.filter((item) => item.attempt?.status === 'interrupted').length,
    submitted_count: candidates.filter((item) => item.attempt?.status === 'submitted').length,
    terminated_count: candidates.filter((item) => item.attempt?.status === 'terminated').length,
    late_start_required_count: candidates.filter((item) => item.late_start_required).length,
    offset: 0,
    limit: 50,
    total: candidates.length,
    classes: [{ id: 'class-a', display_name: 'JSS1 A' }],
    candidates,
    ...overrides,
  }
}

describe('Admin roster workspace', () => {
  it('shows only prepared current exam rosters and scopes subjects through academic level first', () => {
    const data = makeAdminData([
      makeExam({ id: 'exam-jss1', title: 'JSS1 Mathematics CA 1' }),
      makeExam({ id: 'exam-jss2-math', title: 'JSS2 Mathematics CA 1', academicLevelId: 'jss2', academicLevelName: 'JSS2', curriculumSubjectId: 'jss2-math' }),
      makeExam({ id: 'exam-jss2-science', title: 'JSS2 Basic Science CA 1', academicLevelId: 'jss2', academicLevelName: 'JSS2', curriculumSubjectId: 'jss2-science', assessmentComponentId: 'science-ca1', subjectName: 'Basic Science', subjectCode: 'BSC' }),
      makeExam({ id: 'draft-exam', title: 'Draft Mathematics Paper', status: 'draft', statusLabel: 'Draft', rosterStatus: 'not_prepared' }),
    ])

    render(<AdminCurrentRostersPage adminData={data} onNavigate={vi.fn()} />)
    expect(screen.getByText('JSS1 Mathematics CA 1')).toBeInTheDocument()
    expect(screen.getByText('JSS2 Mathematics CA 1')).toBeInTheDocument()
    expect(screen.queryByText('Draft Mathematics Paper')).not.toBeInTheDocument()

    const levelFilter = screen.getByRole('combobox', { name: /roster level filter/i })
    const subjectFilter = screen.getByRole('combobox', { name: /roster subject filter/i })
    expect(subjectFilter).toBeDisabled()
    fireEvent.click(levelFilter)
    fireEvent.click(screen.getByRole('option', { name: /^JSS2$/i }))
    expect(subjectFilter).toBeEnabled()
    expect(screen.queryByText('JSS1 Mathematics CA 1')).not.toBeInTheDocument()
    expect(screen.getByText('JSS2 Mathematics CA 1')).toBeInTheDocument()
    expect(screen.getByText('JSS2 Basic Science CA 1')).toBeInTheDocument()
  })

  it('opens the exact examination roster from its ledger card', () => {
    const onNavigate = vi.fn()
    render(<AdminCurrentRostersPage adminData={makeAdminData([makeExam()])} onNavigate={onNavigate} />)
    fireEvent.click(screen.getByRole('button', { name: /open roster for mathematics ca 1 revision 1/i }))
    expect(onNavigate).toHaveBeenCalledWith('roster-detail', { selectedExamId: 'exam-1' })
  })

  it('loads the whole roster by default and renders separate eligibility and exam state', async () => {
    const exam = makeExam()
    const candidates = [candidate()]
    const listExamRoster = vi.fn().mockResolvedValue(rosterPayload(exam, candidates))
    const gateway = { candidates: { listExamRoster }, attempts: {} }

    render(<AdminRosterDetailPage state={{ staff: { selectedExamId: exam.id } }} adminData={makeAdminData([exam])} gateway={gateway} onNavigate={vi.fn()} />)

    await waitFor(() => expect(listExamRoster).toHaveBeenCalledWith('exam-1', { offset: 0, limit: 50 }))
    expect(await screen.findByText('Ada Okafor')).toBeInTheDocument()
    expect(screen.getByText('Not started')).toBeInTheDocument()
    expect(screen.getAllByText('Eligible').length).toBeGreaterThan(0)
  })

  it('replaces block and late-start controls with interrupt after a candidate starts', async () => {
    const exam = makeExam({ status: 'active', statusLabel: 'Active' })
    const writer = candidate({
      attempt: { id: 'attempt-1', status: 'in_progress', started_at: '2026-09-19T09:00:00Z', ended_at: null, end_reason: null },
      late_start_required: false,
    })
    const listExamRoster = vi.fn().mockResolvedValue(rosterPayload(exam, [writer]))
    const gateway = {
      candidates: { listExamRoster },
      attempts: { interruptAttempt: vi.fn(), resumeAttempt: vi.fn() },
    }

    render(<AdminRosterDetailPage state={{ staff: { selectedExamId: exam.id } }} adminData={makeAdminData([exam])} gateway={gateway} onNavigate={vi.fn()} />)
    const row = (await screen.findByText('Ada Okafor')).closest('tr')
    expect(within(row).getByText('Writing')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Interrupt' })).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Block' })).not.toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: /late start/i })).not.toBeInTheDocument()
  })

  it('shows resume for an interrupted candidate', async () => {
    const exam = makeExam({ status: 'active', statusLabel: 'Active' })
    const paused = candidate({ attempt: { id: 'attempt-2', status: 'interrupted', started_at: '2026-09-19T09:00:00Z', ended_at: null, end_reason: null } })
    const gateway = { candidates: { listExamRoster: vi.fn().mockResolvedValue(rosterPayload(exam, [paused])) }, attempts: { interruptAttempt: vi.fn(), resumeAttempt: vi.fn() } }
    render(<AdminRosterDetailPage state={{ staff: { selectedExamId: exam.id } }} adminData={makeAdminData([exam])} gateway={gateway} onNavigate={vi.fn()} />)
    const row = (await screen.findByText('Ada Okafor')).closest('tr')
    expect(within(row).getByText('Interrupted')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Resume' })).toBeInTheDocument()
  })

  it('keeps lifecycle controls accessible for suspended exams and dismisses the operations menu', async () => {
    const exam = makeExam({ status: 'suspended', statusLabel: 'Suspended' })
    const onNavigate = vi.fn()
    const gateway = { candidates: { listExamRoster: vi.fn().mockResolvedValue(rosterPayload(exam, [candidate()])) } }
    render(<AdminRosterDetailPage state={{ staff: { selectedExamId: exam.id } }} adminData={makeAdminData([exam])} gateway={gateway} onNavigate={onNavigate} />)
    await screen.findByText('Ada Okafor')
    const trigger = screen.getByRole('button', { name: 'Open roster operations' })
    fireEvent.click(trigger)
    expect(screen.getByRole('menuitem', { name: /exam lifecycle controls/i })).toHaveFocus()
    expect(screen.queryByRole('menuitem', { name: /interrupt active attempts/i })).not.toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()

    fireEvent.click(trigger)
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('menuitem', { name: /exam lifecycle controls/i }))
    expect(onNavigate).toHaveBeenCalledWith('operation-detail', { selectedExamId: exam.id })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('offers only state-valid active bulk actions and sends one shared reason', async () => {
    const exam = makeExam({ status: 'active', statusLabel: 'Active' })
    const writer = candidate({ attempt: { id: 'attempt-1', status: 'in_progress', started_at: '2026-09-19T09:00:00Z', ended_at: null, end_reason: null } })
    const late = candidate({ id: 'candidate-2', display_name: 'Bola James', admission_number: 'JSS1/002', student_id: 'student-2', enrollment_id: 'enrollment-2', late_start_required: true })
    const response = rosterPayload(exam, [writer, late])
    const listExamRoster = vi.fn().mockResolvedValue(response)
    const interruptAttempts = vi.fn().mockResolvedValue({ updated_count: 1 })
    const gateway = {
      candidates: { listExamRoster, bulkBlockCandidates: vi.fn(), bulkGrantLateStart: vi.fn() },
      attempts: { interruptAttempt: vi.fn(), resumeAttempt: vi.fn(), interruptAttempts },
    }

    render(<AdminRosterDetailPage state={{ staff: { selectedExamId: exam.id } }} adminData={makeAdminData([exam])} gateway={gateway} onNavigate={vi.fn()} />)
    await screen.findByText('Ada Okafor')
    fireEvent.click(screen.getByRole('button', { name: /open roster operations/i }))
    expect(screen.getByRole('menuitem', { name: /grant late-start access/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /interrupt active attempts/i })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: /bulk block/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('menuitem', { name: /interrupt active attempts/i }))
    expect(screen.getAllByRole('region', { name: /bulk interrupt attempts selection/i })).toHaveLength(1)
    fireEvent.click(screen.getByRole('checkbox', { name: /select ada okafor/i }))
    expect(screen.getAllByRole('button', { name: /continue \(1\)/i })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: /continue \(1\)/i }))
    fireEvent.change(screen.getByPlaceholderText(/one reason for this bulk action/i), { target: { value: 'Network instability in Lab 2' } })
    fireEvent.click(screen.getByRole('button', { name: /^Interrupt 1$/i }))

    await waitFor(() => expect(interruptAttempts).toHaveBeenCalledWith('exam-1', ['attempt-1'], 'Network instability in Lab 2'))
  })
})
