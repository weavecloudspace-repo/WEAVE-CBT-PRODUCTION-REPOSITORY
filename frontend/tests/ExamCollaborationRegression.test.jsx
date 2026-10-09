import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TeacherExamsPage } from '../src/features/teacher/TeacherExamsPage'
import { ExamAuthoringPage } from '../src/shared/exams/ExamAuthoringPage'

const state = {
  session: { actor: { id: 'actor-b', role: 'teacher', display_name: 'Teacher B' } },
  staff: { selectedExamId: null },
}

function makeExam(overrides = {}) {
  return {
    id: 'exam-1',
    sessionId: 'session-1',
    termId: 'term-1',
    title: 'JSS1 English Exam',
    academicLevelId: 'level-jss1',
    academicLevelName: 'JSS1',
    subjectName: 'English',
    curriculumSubjectId: 'subject-1',
    assessmentSchemeId: 'scheme-1',
    assessmentComponentId: 'component-1',
    assessmentName: 'EXAM',
    questionBankId: 'bank-1',
    questionCount: 20,
    selectionMode: 'random',
    durationMinutes: 45,
    shuffleQuestions: true,
    shuffleOptions: true,
    instructions: '',
    folderColor: '#b77915',
    status: 'draft',
    statusLabel: 'Draft',
    authoringVersion: 2,
    revisionNumber: 1,
    leadTeacherId: 'teacher-a',
    scheduledStartAt: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
    latestNormalStartAt: new Date(Date.now() + (24 * 60 + 14) * 60 * 1000).toISOString(),
    createdAt: '2026-09-23T18:00:00.000Z',
    updatedAt: '2026-09-23T18:30:00.000Z',
    ...overrides,
  }
}

function makeTeacherData(exam, assignmentTeacherId = 'teacher-b') {
  return {
    exams: [exam],
    assignments: [{ teacherMembershipId: assignmentTeacherId, curriculumSubjectId: 'subject-1' }],
    subjects: [{
      id: 'subject-1',
      academicLevelId: 'level-jss1',
      academicLevelName: 'JSS1',
      academicLevelCategory: 'junior_secondary',
      academicLevelPosition: 1,
      name: 'English',
      code: 'ENG',
    }],
    banks: [{
      id: 'bank-1',
      curriculumSubjectId: 'subject-1',
      academicLevelId: 'level-jss1',
      academicLevelName: 'JSS1',
      subjectName: 'English',
      name: 'JSS1 English',
      count: 40,
      activeQuestionCount: 40,
    }],
    assessmentSchemes: [{ id: 'scheme-1', name: '2026/2027 Scheme', status: 'active' }],
    assessmentComponents: [{ id: 'component-1', schemeId: 'scheme-1', name: 'EXAM', maximumScore: 70 }],
    session: { id: 'session-1', name: '2026/2027' },
    term: { id: 'term-1', name: 'First Term' },
    loading: false,
    error: '',
    warning: '',
    refresh: vi.fn().mockResolvedValue(undefined),
  }
}

function question(id, prompt) {
  return {
    id,
    prompt,
    instruction: '',
    question_type: 'multiple_choice',
    is_active: true,
    author_name: 'Teacher B',
    image_asset_id: null,
    options: [],
  }
}

function managedQuestionGateway({ selections = [], questions = [] } = {}) {
  const updateExam = vi.fn().mockResolvedValue({ authoring_version: 3 })
  const saveExamQuestionAuthoring = vi.fn().mockResolvedValue({ authoring_version: 4 })
  return {
    updateExam,
    saveExamQuestionAuthoring,
    gateway: {
      exams: {
        updateExam,
        saveExamQuestionAuthoring,
        listManualQuestions: vi.fn().mockResolvedValue(selections),
        getExam: vi.fn().mockResolvedValue({ authoring_version: 2 }),
      },
      questions: {
        listQuestionsForBank: vi.fn().mockResolvedValue(questions),
      },
    },
  }
}

describe('shared examination collaboration guidance', () => {
  it('explains that a random shared draft needs no collaborator question configuration', () => {
    const exam = makeExam({ selectionMode: 'random' })
    render(
      <TeacherExamsPage
        state={state}
        dispatch={vi.fn()}
        teacherData={makeTeacherData(exam)}
        gateway={{ exams: {} }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /lifecycle actions for jss1 english exam/i }))

    expect(screen.getByText(/uses Random selection/i)).toBeInTheDocument()
    expect(screen.getByText(/you do not need to add or configure questions/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /contribute questions/i })).not.toBeInTheDocument()
  })

  it('shows an eligible non-lead the manual contribution action directly on the exam card', () => {
    const dispatch = vi.fn()
    const exam = makeExam({ selectionMode: 'manual' })
    render(
      <TeacherExamsPage
        state={state}
        dispatch={dispatch}
        teacherData={makeTeacherData(exam)}
        gateway={{ exams: {} }}
      />,
    )

    const contributionButton = screen.getByRole('button', { name: /contribute questions/i })
    expect(contributionButton).toBeVisible()
    fireEvent.click(contributionButton)

    expect(dispatch).toHaveBeenCalledWith({
      type: 'staff',
      patch: { section: 'create-exam', selectedExamId: 'exam-1' },
    })
  })
})

describe('exam question configuration saves', () => {
  it('does not resend an unchanged schedule and saves the resulting question setup atomically', async () => {
    const exam = makeExam({
      selectionMode: 'random',
      leadTeacherId: 'teacher-b',
    })
    const teacherData = makeTeacherData(exam, 'teacher-b')
    const { gateway, updateExam, saveExamQuestionAuthoring } = managedQuestionGateway()
    const dispatch = vi.fn()

    render(
      <ExamAuthoringPage
        state={{ ...state, staff: { selectedExamId: 'exam-1' } }}
        dispatch={dispatch}
        teacherData={teacherData}
        gateway={gateway}
      />,
    )

    fireEvent.click(screen.getByRole('radio', { name: /manual selection/i }))
    const saveButton = screen.getByRole('button', { name: /save changes/i })
    await waitFor(() => expect(saveButton).toBeEnabled())
    fireEvent.click(saveButton)

    await waitFor(() => expect(updateExam).toHaveBeenCalledTimes(1))
    const [, payload] = updateExam.mock.calls[0]
    expect(payload).not.toHaveProperty('scheduled_start_at')
    expect(payload).not.toHaveProperty('latest_normal_start_at')

    await waitFor(() => expect(saveExamQuestionAuthoring).toHaveBeenCalledWith('exam-1', {
      question_bank_id: 'bank-1',
      question_selection_mode: 'manual',
      question_count: 20,
      manual_question_ids: [],
      expected_authoring_version: 3,
    }))
  })

  it('lets a manager increase the question count and stage the extra manual picks before saving', async () => {
    const exam = makeExam({
      selectionMode: 'manual',
      questionCount: 3,
      leadTeacherId: 'teacher-b',
    })
    const questionRows = [
      question('question-1', 'Question one'),
      question('question-2', 'Question two'),
      question('question-3', 'Question three'),
      question('question-4', 'Question four'),
      question('question-5', 'Question five'),
    ]
    const selections = questionRows.slice(0, 3).map((row, index) => ({
      question_id: row.id,
      added_by_actor_id: 'actor-original',
      position: index + 1,
    }))
    const teacherData = makeTeacherData(exam, 'teacher-b')
    const { gateway, saveExamQuestionAuthoring } = managedQuestionGateway({
      selections,
      questions: questionRows,
    })

    render(
      <ExamAuthoringPage
        state={{ ...state, staff: { selectedExamId: 'exam-1' } }}
        dispatch={vi.fn()}
        teacherData={teacherData}
        gateway={gateway}
      />,
    )

    await screen.findByRole('button', { name: 'Remove question from exam: Question one' })
    fireEvent.change(screen.getByRole('spinbutton', { name: /number of questions/i }), {
      target: { value: '5' },
    })

    const fourth = screen.getByRole('checkbox', { name: 'Select question: Question four' })
    const fifth = screen.getByRole('checkbox', { name: 'Select question: Question five' })
    expect(fourth).toBeEnabled()
    expect(fifth).toBeEnabled()

    fireEvent.click(fourth)
    fireEvent.click(fifth)

    expect(saveExamQuestionAuthoring).not.toHaveBeenCalled()
    expect(screen.getByText('5 / 5 selected')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(saveExamQuestionAuthoring).toHaveBeenCalledWith('exam-1', {
      question_bank_id: 'bank-1',
      question_selection_mode: 'manual',
      question_count: 5,
      manual_question_ids: [
        'question-1',
        'question-2',
        'question-3',
        'question-4',
        'question-5',
      ],
      expected_authoring_version: 3,
    }))
  })
})
