import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { TeacherExamsPage } from '../src/features/teacher/TeacherExamsPage'

import { ExamHistoryPage } from '../src/shared/exams/ExamHistoryPage'

import { ExamAuthoringPage } from '../src/shared/exams/ExamAuthoringPage'

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }
})

const teacherData = {
  exams: [
    {
      id: 'exam-1',
      title: 'Mathematics CA 1',
      subjectName: 'Mathematics',
      curriculumSubjectId: 'subject-1',
      assessmentSchemeId: 'scheme-1',
      assessmentComponentId: 'component-1',
      assessmentName: 'CA 1',
      questionBankId: 'bank-1',
      questionCount: 30,
      selectionMode: 'manual',
      durationMinutes: 45,
      shuffleQuestions: true,
      shuffleOptions: true,
      instructions: '',
      folderColor: '#397fd6',
      status: 'draft',
      statusLabel: 'Draft',
      updatedAt: '2026-09-16T10:00:00Z',
      authoringVersion: 3,
      revisionNumber: 1,
      createdByActorId: 'actor-1',
      leadTeacherId: 'teacher-1',
      rosterCandidateCount: 0,
      scheduledStartAt: null,
      latestNormalStartAt: null,
    },
  ],
  assignments: [{ teacherMembershipId: 'teacher-1', curriculumSubjectId: 'subject-1' }],
  subjects: [
    {
      id: 'subject-1',
      academicLevelId: 'level-jss1',
      academicLevelName: 'JSS1',
      academicLevelCategory: 'junior_secondary',
      academicLevelPosition: 1,
      name: 'Mathematics',
      code: 'MTH',
    },
  ],
  banks: [
    {
      id: 'bank-1',
      curriculumSubjectId: 'subject-1',
      academicLevelId: 'level-jss1',
      academicLevelName: 'JSS1',
      subjectName: 'Mathematics',
      name: 'Mathematics Bank',
      count: 40,
      activeQuestionCount: 40,
    },
  ],
  assessmentSchemes: [
    { id: 'scheme-1', name: 'Standard Scheme', status: 'active' },
  ],
  assessmentComponents: [
    {
      id: 'component-1',
      schemeId: 'scheme-1',
      name: 'CA 1',
      maximumScore: 10,
    },
  ],
  session: { id: 'session-1', name: '2026/2027' },
  term: { id: 'term-1', name: 'First Term' },
  loading: false,
  error: '',
  warning: '',
  refresh: vi.fn().mockResolvedValue(undefined),
}

const teacherState = {
  session: { actor: { id: 'actor-1', role: 'teacher' } },
  staff: { selectedExamId: null },
}

function chooseSelectOption(label, optionName) {
  fireEvent.click(screen.getByRole('combobox', { name: label }))
  fireEvent.click(screen.getByRole('option', { name: optionName }))
}

function completeNewExamContext() {
  chooseSelectOption(/academic level/i, /JSS1/i)
  chooseSelectOption(/^subject$/i, /Mathematics/i)
  chooseSelectOption(/assessment component/i, /CA 1/i)
  chooseSelectOption(/question bank/i, /Mathematics Bank/i)
}

describe('Teacher exams', () => {
  it('suggests twenty minutes for entry, preserves adjustments, and respects clearing', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T06:00:00'))
    try {
      render(<ExamAuthoringPage state={teacherState} dispatch={vi.fn()} teacherData={{ ...teacherData, exams: [] }} gateway={{ exams: {} }} />)
      const setTime = (label, hour, minute) => {
        fireEvent.click(screen.getByRole('button', { name: label }))
        chooseSelectOption(`${label} hour`, hour)
        chooseSelectOption(`${label} minute`, minute)
        fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
      }
      const expectDeadline = (hour, minute) => {
        const expected = new Date(`2026-09-23T${hour}:${minute}`).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
        expect(screen.getByRole('button', { name: 'Normal entry deadline' })).toHaveTextContent(expected)
      }
      setTime('Scheduled start', '08', '00')
      expectDeadline('08', '20')
      setTime('Normal entry deadline', '08', '35')
      setTime('Scheduled start', '09', '00')
      expectDeadline('09', '35')
      fireEvent.click(screen.getByRole('button', { name: 'Normal entry deadline' }))
      fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
      setTime('Scheduled start', '10', '00')
      expect(screen.getByRole('button', { name: 'Normal entry deadline' })).toHaveTextContent('Choose date & time')
    } finally {
      vi.useRealTimers()
    }
  })

  it('renders a readable exam collection and opens the create workflow', () => {
    const dispatch = vi.fn()
    render(
      <TeacherExamsPage
        state={teacherState}
        dispatch={dispatch}
        teacherData={teacherData}
        gateway={{ exams: {} }}
      />,
    )

    expect(screen.getByRole('heading', { name: /examinations/i })).toBeInTheDocument()
    const examHeading = screen.getByRole('heading', { name: 'Mathematics CA 1' })
    expect(examHeading).toBeInTheDocument()
    const examCard = examHeading.closest('article')
    expect(examCard).not.toBeNull()
    expect(within(examCard).getByText('Draft')).toBeInTheDocument()
    expect(within(examCard).getByText(/30 questions/)).toHaveTextContent('45 min')

    fireEvent.click(screen.getByRole('button', { name: /^create exam$/i }))
    expect(dispatch).toHaveBeenCalledWith({
      type: 'staff',
      patch: { section: 'create-exam', selectedExamId: null },
    })
  })

  it('starts a fresh exam form without inherited level, subject, component or bank', async () => {
    const dispatch = vi.fn()
    const createExam = vi.fn().mockResolvedValue({ id: 'exam-new' })
    const refresh = vi.fn().mockResolvedValue(undefined)

    render(
      <ExamAuthoringPage
        state={teacherState}
        dispatch={dispatch}
        teacherData={{ ...teacherData, exams: [], refresh }}
        gateway={{ exams: { createExam } }}
      />,
    )

    expect(screen.getByRole('combobox', { name: /academic level/i })).toHaveTextContent('Choose level')
    expect(screen.getByRole('combobox', { name: /^subject$/i })).toHaveTextContent('Choose a level first')
    expect(screen.getByRole('combobox', { name: /^subject$/i })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: /assessment scheme/i })).toHaveTextContent('Standard Scheme')
    expect(screen.getByRole('combobox', { name: /assessment component/i })).toHaveTextContent('Choose component')
    expect(screen.getByRole('combobox', { name: /question bank/i })).toHaveTextContent('Choose a subject first')
    expect(screen.getByRole('button', { name: /create draft exam/i })).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/exam title/i), {
      target: { value: 'Mathematics Mid Term' },
    })
    completeNewExamContext()
    expect(screen.getByRole('button', { name: /create draft exam/i })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: /create draft exam/i }))

    await waitFor(() => expect(createExam).toHaveBeenCalledTimes(1))
    expect(createExam).toHaveBeenCalledWith({
      session_id: 'session-1',
      term_id: 'term-1',
      curriculum_subject_id: 'subject-1',
      assessment_scheme_id: 'scheme-1',
      assessment_component_id: 'component-1',
      question_bank_id: 'bank-1',
      question_selection_mode: 'random',
      question_count: 20,
      title: 'Mathematics Mid Term',
      instructions: null,
      folder_color: '#8190a5',
      duration_minutes: 45,
      shuffle_questions: true,
      shuffle_options: true,
      scheduled_start_at: null,
      latest_normal_start_at: null,
    })
    expect(refresh).toHaveBeenCalled()
    expect(dispatch).toHaveBeenCalledWith({
      type: 'staff',
      patch: { section: 'exams', selectedExamId: null, examAuthoringNotice: '' },
    })
  })

  it('adds manually chosen bank questions to the new draft using its returned version', async () => {
    const createExam = vi.fn().mockResolvedValue({ id: 'created-exam', authoring_version: 4 })
    const addManualQuestions = vi.fn().mockResolvedValue({ authoring_version: 5 })
    const questions = [{ id: 'question-1', prompt: 'What is two plus two?', question_type: 'single_choice', is_active: true, options: [] }]
    render(<ExamAuthoringPage state={teacherState} dispatch={vi.fn()} teacherData={{ ...teacherData, exams: [] }} gateway={{ exams: { createExam, addManualQuestions }, questions: { listQuestionsForBank: vi.fn().mockResolvedValue(questions) } }} />)
    fireEvent.change(screen.getByLabelText('Exam title'), { target: { value: 'Manual paper' } })
    completeNewExamContext()
    fireEvent.click(screen.getByRole('radio', { name: /manual selection/i }))
    fireEvent.click(await screen.findByRole('checkbox', { name: /two plus two/i }))
    fireEvent.click(screen.getByRole('button', { name: /create draft exam/i }))
    await waitFor(() => expect(addManualQuestions).toHaveBeenCalledWith('created-exam', ['question-1'], 4))
    expect(createExam).toHaveBeenCalledWith(expect.objectContaining({ question_selection_mode: 'manual' }))
  })

  it('opens the already created draft when adding its manual questions fails', async () => {
    const dispatch = vi.fn()
    const createExam = vi.fn().mockResolvedValue({ id: 'created-exam', authoring_version: 1 })
    const addManualQuestions = vi.fn().mockRejectedValue({ userMessage: 'Question was archived.' })
    render(<ExamAuthoringPage state={teacherState} dispatch={dispatch} teacherData={{ ...teacherData, exams: [] }} gateway={{ exams: { createExam, addManualQuestions }, questions: { listQuestionsForBank: vi.fn().mockResolvedValue([{ id: 'question-1', prompt: 'Choose me', question_type: 'single_choice', is_active: true, options: [] }]) } }} />)
    fireEvent.change(screen.getByLabelText('Exam title'), { target: { value: 'Manual paper' } })
    completeNewExamContext()
    fireEvent.click(screen.getByRole('radio', { name: /manual selection/i }))
    fireEvent.click(await screen.findByRole('checkbox', { name: /Choose me/i }))
    fireEvent.click(screen.getByRole('button', { name: /create draft exam/i }))
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'create-exam', selectedExamId: 'created-exam', examAuthoringNotice: expect.stringContaining('Question was archived.') } }))
    expect(createExam).toHaveBeenCalledTimes(1)
  })

  it('resets dependent choices when the academic level or subject changes', () => {
    const scopedData = {
      ...teacherData,
      exams: [],
      subjects: [
        ...teacherData.subjects,
        {
          id: 'subject-2',
          academicLevelId: 'level-jss2',
          academicLevelName: 'JSS2',
          academicLevelCategory: 'junior_secondary',
          academicLevelPosition: 2,
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
      banks: [
        ...teacherData.banks,
        {
          id: 'bank-2',
          curriculumSubjectId: 'subject-2',
          academicLevelId: 'level-jss2',
          academicLevelName: 'JSS2',
          subjectName: 'Mathematics',
          name: 'JSS2 Mathematics Bank',
          count: 30,
          activeQuestionCount: 30,
        },
        {
          id: 'bank-3',
          curriculumSubjectId: 'subject-3',
          academicLevelId: 'level-jss2',
          academicLevelName: 'JSS2',
          subjectName: 'Basic Science',
          name: 'JSS2 Science Bank',
          count: 25,
          activeQuestionCount: 25,
        },
      ],
    }

    render(
      <ExamAuthoringPage
        state={teacherState}
        dispatch={vi.fn()}
        teacherData={scopedData}
        gateway={{ exams: { createExam: vi.fn() } }}
      />,
    )

    const levelSelect = screen.getByRole('combobox', { name: /academic level/i })
    expect(levelSelect).toHaveTextContent('Choose level')
    expect(screen.getByRole('combobox', { name: /^subject$/i })).toBeDisabled()

    fireEvent.click(levelSelect)
    fireEvent.click(screen.getByRole('option', { name: /JSS2/i }))

    expect(screen.getByRole('combobox', { name: /^subject$/i })).toHaveTextContent('Choose subject')
    fireEvent.click(screen.getByRole('combobox', { name: /^subject$/i }))
    expect(screen.getByRole('option', { name: /Basic Science/i })).toBeInTheDocument()
    expect(screen.getAllByRole('option', { name: /Mathematics/i })).toHaveLength(1)

    fireEvent.click(screen.getByRole('option', { name: /Basic Science/i }))
    expect(screen.getByRole('combobox', { name: /question bank/i })).toHaveTextContent('Choose bank')
    fireEvent.click(screen.getByRole('combobox', { name: /question bank/i }))
    expect(screen.getByRole('option', { name: /JSS2 Science Bank/i })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /^Mathematics Bank/i })).not.toBeInTheDocument()
  })

  it('requires confirmation before clearing saved manual selections when switching a draft to random', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const updateExam = vi.fn().mockResolvedValue({ authoring_version: 4 })
    const saveExamQuestionAuthoring = vi.fn().mockResolvedValue({ authoring_version: 5 })
    const selections = [
      { question_id: 'question-1', added_by_actor_id: 'actor-1' },
      { question_id: 'question-2', added_by_actor_id: 'actor-2' },
    ]
    const gateway = {
      questions: { listQuestionsForBank: vi.fn().mockResolvedValue([]) },
      exams: {
        getExam: vi.fn().mockResolvedValue({ authoring_version: 3 }),
        listManualQuestions: vi.fn().mockResolvedValue(selections),
        updateExam,
        saveExamQuestionAuthoring,
      },
    }
    const editState = { ...teacherState, staff: { selectedExamId: 'exam-1' } }

    render(<ExamAuthoringPage state={editState} dispatch={vi.fn()} teacherData={teacherData} gateway={gateway} />)
    fireEvent.click(screen.getByRole('radio', { name: /random selection/i }))
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledTimes(1))
    expect(confirmSpy.mock.calls[0][0]).toContain('2 manually selected questions from 2 contributors')
    expect(updateExam).not.toHaveBeenCalled()
    expect(saveExamQuestionAuthoring).not.toHaveBeenCalled()

    await waitFor(() => expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled())
    confirmSpy.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(saveExamQuestionAuthoring).toHaveBeenCalledWith('exam-1', {
      question_bank_id: 'bank-1',
      question_selection_mode: 'random',
      question_count: 30,
      manual_question_ids: [],
      expected_authoring_version: 4,
    }))
    expect(updateExam).toHaveBeenCalledTimes(1)
    confirmSpy.mockRestore()
  })

  it('uses the current authoring version when submitting a draft', async () => {
    const dispatch = vi.fn()
    const submitExam = vi.fn().mockResolvedValue({})
    const refresh = vi.fn().mockResolvedValue(undefined)

    render(
      <TeacherExamsPage
        state={teacherState}
        dispatch={dispatch}
        teacherData={{ ...teacherData, refresh }}
        gateway={{ exams: { submitExam, deleteDraftExam: vi.fn() } }}
      />,
    )

    fireEvent.click(
      screen.getByRole('button', {
        name: /lifecycle actions for mathematics ca 1/i,
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: /submit for review/i }))
    fireEvent.click(screen.getByRole('button', { name: /^submit for review$/i }))

    await waitFor(() => expect(submitExam).toHaveBeenCalledWith('exam-1', 3))
    expect(refresh).toHaveBeenCalled()
  })
})

it('opens the latest existing scope regardless of title from creation', () => {
  const dispatch = vi.fn()
  const data = { ...teacherData, exams: [
    { ...teacherData.exams[0], termId: 'term-1', status: 'closed' },
    { ...teacherData.exams[0], termId: 'term-1', id: 'revision-2', title: 'Different title', revisionNumber: 2 },
  ] }
  render(<ExamAuthoringPage state={teacherState} dispatch={dispatch} teacherData={data} gateway={{}} />)
  completeNewExamContext()
  fireEvent.click(screen.getByRole('button', { name: 'Open Existing Examination' }))
  expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'exam-history', selectedExamId: 'revision-2', examAuthoringNotice: '' } })
})

it('shows preserved revisions on a dedicated page with an authorized draft editor', () => {
  const dispatch = vi.fn()
  const data = { ...teacherData, exams: [
    { ...teacherData.exams[0], selectionMode: 'random', status: 'closed', statusLabel: 'Closed' },
    { ...teacherData.exams[0], id: 'revision-2', revisionNumber: 2 },
  ] }
  render(<ExamHistoryPage state={{ ...teacherState, staff: { selectedExamId: 'exam-1' } }} dispatch={dispatch} teacherData={data} gateway={{}} />)
  expect(screen.queryByRole('textbox', { name: 'Exam title' })).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Revision 1' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Revision 2' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Edit current draft/ }))
  expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'create-exam', selectedExamId: 'revision-2', examAuthoringNotice: '' } })
})

it('recovers a duplicate committed after the create form loaded', async () => {
  const dispatch = vi.fn()
  const data = { ...teacherData, exams: [] }
  const gateway = { exams: {
    createExam: vi.fn().mockRejectedValue({ status: 409, userMessage: 'An examination already exists' }),
    listExams: vi.fn().mockResolvedValue({ exams: [{ id: 'concurrent-revision', revision_number: 2 }], total: 1 }),
  } }
  render(<ExamAuthoringPage state={teacherState} dispatch={dispatch} teacherData={data} gateway={gateway} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'Exam title' }), { target: { value: 'A different title' } })
  completeNewExamContext()
  fireEvent.submit(screen.getByRole('textbox', { name: 'Exam title' }).closest('form'))
  fireEvent.click(await screen.findByRole('button', { name: 'Open Existing Examination' }))
  expect(gateway.exams.listExams).toHaveBeenCalledWith({ term_id: 'term-1', curriculum_subject_id: 'subject-1', assessment_component_id: 'component-1', offset: 0, limit: 200 })
  expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'exam-history', selectedExamId: 'concurrent-revision', examAuthoringNotice: '' } })
})

it('separates opening the history from editing a draft on the card', () => {
  const dispatch = vi.fn()
  render(<TeacherExamsPage state={teacherState} dispatch={dispatch} teacherData={teacherData} gateway={{ exams: {} }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Open Mathematics CA 1' }))
  expect(dispatch).toHaveBeenLastCalledWith({ type: 'staff', patch: { section: 'exam-history', selectedExamId: 'exam-1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Edit Mathematics CA 1' }))
  expect(dispatch).toHaveBeenLastCalledWith({ type: 'staff', patch: { section: 'create-exam', selectedExamId: 'exam-1' } })
})
