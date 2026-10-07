import { ToastHost } from '../src/shared/ui/ToastHost'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ExamOperations, ExamOperationsDetail } from '../src/features/admin/pages/ExamOperations'

function todayAt(hour = 9, minute = 0) {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate(), hour, minute, 0).toISOString()
}

function makeSubject(overrides = {}) {
  return {
    id: 'jss1-english',
    academicLevelId: 'jss1',
    academicLevelName: 'JSS1',
    academicLevelCategory: 'junior_secondary',
    academicLevelPosition: 1,
    name: 'English Language',
    code: 'ENG',
    ...overrides,
  }
}

function makeExam(overrides = {}) {
  return {
    id: 'exam-1',
    title: 'English CA 1',
    academicLevelId: 'jss1',
    academicLevelName: 'JSS1',
    subjectName: 'English Language',
    subjectCode: 'ENG',
    curriculumSubjectId: 'jss1-english',
    assessmentName: 'CA 1',
    status: 'sealed',
    statusLabel: 'Sealed',
    rosterStatus: 'ready',
    rosterVersion: 2,
    rosterCandidateCount: 126,
    rosterPreparedAt: todayAt(7),
    rosterError: '',
    revisionNumber: 1,
    scheduledStartAt: todayAt(9),
    latestNormalStartAt: todayAt(9, 15),
    durationMinutes: 45,
    questionCount: 30,
    ...overrides,
  }
}

function makeAdminData(exams) {
  return {
    exams,
    subjects: [
      makeSubject(),
      makeSubject({
        id: 'jss2-math',
        academicLevelId: 'jss2',
        academicLevelName: 'JSS2',
        academicLevelPosition: 2,
        name: 'Mathematics',
        code: 'MTH',
      }),
    ],
    loading: false,
    error: '',
    warning: '',
    refreshExams: vi.fn().mockResolvedValue(undefined),
  }
}

function makeGateway() {
  return {
    exams: {
      activationPreflight: vi.fn().mockResolvedValue({ can_activate: true, blockers: [], affected_exams: [] }),
      activateExam: vi.fn().mockResolvedValue({}),
      suspendExam: vi.fn().mockResolvedValue({}),
      resumeExam: vi.fn().mockResolvedValue({}),
      closeExam: vi.fn().mockResolvedValue({}),
      cancelExam: vi.fn().mockResolvedValue({}),
    },
  }
}

describe('Admin exam operations workspace', () => {
  it('shows operational papers on the day-of timetable and excludes unsealed authoring work', () => {
    const data = makeAdminData([
      makeExam(),
      makeExam({ id: 'submitted-1', title: 'Submitted English Paper', status: 'submitted', statusLabel: 'Submitted', rosterStatus: 'not_prepared' }),
    ])

    render(<ExamOperations adminData={data} onNavigate={vi.fn()} />)

    expect(within(screen.getByRole('region', { name: 'Operations timeline' })).getByRole('button', { name: /^English CA 1/ })).toBeInTheDocument()
    expect(screen.queryByText('Submitted English Paper')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Today 1$/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Ready 1$/ })).toBeInTheDocument()
    expect(screen.getByText('Scheduled today')).toBeInTheDocument()
    expect(screen.getByText('Ready to start')).toBeInTheDocument()
  })

  it('keeps level-first subject filtering in the operations workspace', () => {
    const data = makeAdminData([
      makeExam(),
      makeExam({
        id: 'math-exam',
        title: 'JSS2 Mathematics CA 1',
        academicLevelId: 'jss2',
        academicLevelName: 'JSS2',
        subjectName: 'Mathematics',
        curriculumSubjectId: 'jss2-math',
      }),
    ])

    render(<ExamOperations adminData={data} onNavigate={vi.fn()} />)

    const levelFilter = screen.getByRole('combobox', { name: /operations level filter/i })
    const subjectFilter = screen.getByRole('combobox', { name: /operations subject filter/i })
    expect(subjectFilter).toBeDisabled()

    fireEvent.click(levelFilter)
    fireEvent.click(screen.getByRole('option', { name: /^JSS2$/i }))

    expect(subjectFilter).toBeEnabled()
    expect(screen.queryByText('English CA 1')).not.toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Operations timeline' })).getByRole('button', { name: /^JSS2 Mathematics CA 1/ })).toBeInTheDocument()
  })


  it('uses the selected date for readiness and excludes stale rosters from the ready view', () => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)

    const data = makeAdminData([
      makeExam(),
      makeExam({ id: 'tomorrow', title: 'Tomorrow sitting', scheduledStartAt: tomorrow.toISOString() }),
      makeExam({ id: 'stale', title: 'Stale sitting', rosterStatus: 'stale' }),
    ])
    const onNavigate = vi.fn()
    render(<ExamOperations adminData={data} onNavigate={onNavigate} />)
    const readiness = screen.getByRole('region', { name: 'Ready sittings' })
    expect(within(readiness).queryByText('Tomorrow sitting')).not.toBeInTheDocument()
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }
    fireEvent.click(screen.getByRole('button', { name: /^Operations date:/ }))
    if (tomorrow.getMonth() !== new Date().getMonth()) fireEvent.click(screen.getByRole('button', { name: 'Next month' }))
    fireEvent.click(screen.getByRole('button', { name: tomorrow.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }) }))
    expect(within(readiness).getByText('Tomorrow sitting')).toBeInTheDocument()
    expect(within(readiness).queryByText('English CA 1')).not.toBeInTheDocument()
    fireEvent.click(within(readiness).getByRole('button', { name: /open controls/i }))
    expect(onNavigate).toHaveBeenCalledWith('operation-detail', { selectedExamId: 'tomorrow' })
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Operation views' })).getByRole('button', { name: /^Ready/ }))
    expect(within(screen.getByRole('region', { name: 'Operations timeline' })).queryByRole('button', { name: /^Stale sitting/ })).not.toBeInTheDocument()
  })

  it('shows heartbeat-based activity and routes connection checks to the selected roster', async () => {
    const data = makeAdminData([makeExam({ status: 'active' })])
    const gateway = makeGateway()
    gateway.exams.listExamAttempts = vi.fn().mockResolvedValue({ total: 2, attempts: [
      { id: 'online', candidate_name: 'Ada Example', admission_number: '001', status: 'in_progress', connectivity: 'online', heartbeat_age_seconds: 3 },
      { id: 'offline', candidate_name: 'Bola Example', admission_number: '002', status: 'interrupted', connectivity: 'stale', heartbeat_age_seconds: 180 },
    ] })
    const onNavigate = vi.fn()
    render(<ExamOperations adminData={data} gateway={gateway} onNavigate={onNavigate} />)
    expect(await screen.findByText('Ada Example')).toBeInTheDocument()
    expect(screen.getByText('Bola Example')).toBeInTheDocument()
    const activity = screen.getByText('Candidate activity').closest('details')
    expect(activity).not.toHaveAttribute('open')
    fireEvent.click(within(activity).getByText('Candidate activity'))
    expect(activity).toHaveAttribute('open')
    expect(screen.getByText('1 candidate needs a connection check')).toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('region', { name: 'Attention queue' })).getByRole('button', { name: 'Review' }))
    expect(onNavigate).toHaveBeenCalledWith('roster-detail', { selectedExamId: 'exam-1' })
    expect(gateway.exams.listExamAttempts).toHaveBeenCalledWith('exam-1', { offset: 0, limit: 200 }, { signal: expect.any(AbortSignal) })
  })

  it('does not present a failed monitoring request as zero online candidates', async () => {
    const gateway = makeGateway()
    gateway.exams.listExamAttempts = vi.fn().mockRejectedValue(new Error('unavailable'))
    render(<ExamOperations adminData={makeAdminData([makeExam({ status: 'active' })])} gateway={gateway} onNavigate={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/candidate monitoring could not refresh/i)
    expect(screen.queryByText(/0 attempts started/)).not.toBeInTheDocument()
  })

  it('selects active sittings in the timeline and suspends them in one batch', async () => {
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
    const data = makeAdminData([
      makeExam({ id: 'active-one', title: 'Active English', status: 'active' }),
      makeExam({ id: 'active-two', title: 'Active Mathematics', status: 'active' }),
      makeExam({ id: 'sealed', title: 'Sealed Literature' }),
    ])
    const gateway = makeGateway()
    gateway.exams.batchExamOperation = vi.fn().mockResolvedValue({ results: [
      { exam_id: 'active-one', succeeded: true, status: 'suspended' },
      { exam_id: 'active-two', succeeded: true, status: 'suspended' },
    ] })
    const onNavigate = vi.fn()
    render(<ExamOperations adminData={data} gateway={gateway} onNavigate={onNavigate} />)
    const timeline = screen.getByRole('region', { name: 'Operations timeline' })
    fireEvent.click(within(timeline).getByRole('button', { name: 'Bulk operations' }))
    fireEvent.click(screen.getByRole('menuitem', { name: /^Suspend examinations/ }))
    expect(screen.getByLabelText('Select Sealed Literature')).toBeDisabled()
    fireEvent.click(within(timeline).getByRole('button', { name: /^Active English/ }))
    expect(screen.getByLabelText('Select Active English')).toBeChecked()
    fireEvent.click(screen.getByLabelText('Select Active English'))
    expect(screen.getByLabelText('Select Active English')).not.toBeChecked()
    fireEvent.click(screen.getByText('Active English').closest('article'))
    expect(screen.getByLabelText('Select Active English')).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Toggle selection for Active Mathematics' }))
    expect(screen.getByLabelText('Select Active Mathematics')).toBeChecked()
    fireEvent.click(screen.getByText('Sealed Literature').closest('article'))
    expect(screen.getByLabelText('Select Sealed Literature')).not.toBeChecked()
    expect(onNavigate).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Continue (2)' }))
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'Power outage' } })
    fireEvent.click(screen.getByRole('button', { name: 'Suspend selected examinations' }))
    await screen.findByText('2 succeeded · 0 need review')
    expect(gateway.exams.batchExamOperation).toHaveBeenCalledWith('suspend', ['active-one', 'active-two'], 'Power outage')
  })

  it('activates a sealed examination from the operations control room', async () => {
    const exam = makeExam()
    const data = makeAdminData([exam])
    const gateway = makeGateway()

    render(
      <ExamOperationsDetail
        state={{ staff: { selectedExamId: exam.id } }}
        adminData={data}
        gateway={gateway}
        onNavigate={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /activate examination/i }))
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent(/activate this examination/i)
    await waitFor(() => expect(within(dialog).getByRole('button', { name: /^activate examination$/i })).toBeEnabled())
    fireEvent.click(within(dialog).getByRole('button', { name: /^activate examination$/i }))

    await waitFor(() => expect(gateway.exams.activateExam).toHaveBeenCalledWith('exam-1'))
    expect(data.refreshExams).toHaveBeenCalled()
  })

  it('requires an audit reason before suspending a live examination', async () => {
    render(<ToastHost />)
    const exam = makeExam({ status: 'active', statusLabel: 'Active' })
    const data = makeAdminData([exam])
    const gateway = makeGateway()

    render(
      <ExamOperationsDetail
        state={{ staff: { selectedExamId: exam.id } }}
        adminData={data}
        gateway={gateway}
        onNavigate={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /suspend examination/i }))
    const dialog = screen.getByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^suspend examination$/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/enter a reason before continuing/i)
    expect(gateway.exams.suspendExam).not.toHaveBeenCalled()

    fireEvent.change(within(dialog).getByRole('textbox', { name: /reason/i }), { target: { value: 'Network interruption' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /^suspend examination$/i }))

    await waitFor(() => expect(gateway.exams.suspendExam).toHaveBeenCalledWith('exam-1', 'Network interruption'))
  })
})

it('opens the timetable from the operations shortcut', () => {
  const onNavigate = vi.fn()
  render(<ExamOperations adminData={makeAdminData([])} onNavigate={onNavigate} />)
  fireEvent.click(screen.getByRole('button', { name: 'Quick Actions' }))
  fireEvent.click(screen.getByRole('menuitem', { name: /Timetable.*View scheduled examinations by level/i }))
  expect(onNavigate).toHaveBeenCalledWith('timetable')
})

it('dismisses operations quick actions with Escape and outside clicks', () => {
  render(<ExamOperations adminData={makeAdminData([])} onNavigate={vi.fn()} />)
  const trigger = screen.getByRole('button', { name: 'Quick Actions' })
  fireEvent.click(trigger)
  expect(screen.getByRole('menu', { name: 'Operations quick actions' })).toBeInTheDocument()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  fireEvent.click(trigger)
  fireEvent.pointerDown(document.body)
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})
it('scopes every timeline tab, sitting count, and live monitor to the selected date', () => {
  const yesterday = new Date()
  yesterday.setDate(yesterday.getDate() - 1)
  const tomorrow = new Date()
  tomorrow.setDate(tomorrow.getDate() + 1)
  const data = makeAdminData([
    makeExam({ title: 'Selected day paper' }),
    makeExam({ id: 'past-live', title: 'Past live paper', status: 'active', scheduledStartAt: yesterday.toISOString() }),
    makeExam({ id: 'past-closed', title: 'Past closed paper', status: 'closed', scheduledStartAt: yesterday.toISOString() }),
    makeExam({ id: 'future', title: 'Future paper', scheduledStartAt: tomorrow.toISOString() }),
  ])
  render(<ExamOperations adminData={data} onNavigate={vi.fn()} />)
  const tabs = within(screen.getByRole('navigation', { name: 'Operation views' }))
  const timeline = within(screen.getByRole('region', { name: 'Operations timeline' }))
  for (const tab of ['Today', 'Ready', 'Live', 'Upcoming', 'Completed', 'All']) {
    fireEvent.click(tabs.getByRole('button', { name: new RegExp(`^${tab}`) }))
    expect(timeline.queryByText('Past live paper')).not.toBeInTheDocument()
    expect(timeline.queryByText('Past closed paper')).not.toBeInTheDocument()
    expect(timeline.queryByText('Future paper')).not.toBeInTheDocument()
  }
  expect(timeline.getByRole('button', { name: /^Selected day paper/ })).toBeInTheDocument()
  expect(tabs.getByRole('button', { name: /^Live 0$/ })).toBeInTheDocument()
  expect(tabs.getByRole('button', { name: /^Today 1$/ })).toBeInTheDocument()
  expect(screen.getByText('Live examinations').closest('article').querySelector('strong')).toHaveTextContent('0')
  expect(screen.getByText('Scheduled today').closest('article').querySelector('strong')).toHaveTextContent('1')
  expect(within(screen.getByRole('region', { name: 'Live exam status' })).getByText('No live examinations')).toBeInTheDocument()
  expect(screen.queryByText('Past live paper')).not.toBeInTheDocument()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }
  fireEvent.click(screen.getByRole('button', { name: /^Operations date:/ }))
  if (yesterday.getMonth() !== new Date().getMonth()) fireEvent.click(screen.getByRole('button', { name: 'Previous month' }))
  fireEvent.click(screen.getByRole('button', { name: yesterday.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }) }))
  expect(timeline.getByRole('button', { name: /^Past live paper/ })).toBeInTheDocument()
  expect(timeline.getByRole('button', { name: /^Past closed paper/ })).toBeInTheDocument()
  expect(timeline.queryByText('Selected day paper')).not.toBeInTheDocument()
  expect(tabs.getByRole('button', { name: /^Live 1$/ })).toBeInTheDocument()
  expect(screen.getByText('Live examinations').closest('article').querySelector('strong')).toHaveTextContent('1')
  expect(tabs.getByRole('button', { name: /^Selected day 2$/ })).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Live exam status' })).getByText('Past live paper')).toBeInTheDocument()
})
