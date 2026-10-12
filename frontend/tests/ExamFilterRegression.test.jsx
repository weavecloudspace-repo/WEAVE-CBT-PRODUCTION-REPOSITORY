import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TeacherExamsPage } from '../src/features/teacher/TeacherExamsPage'
import { ExamCard } from '../src/shared/exams/ExamCard'

const state = {
  session: { actor: { id: 'actor-1', role: 'teacher' } },
  staff: { selectedExamId: null },
}

function exam(overrides = {}) {
  return {
    id: 'exam-1',
    title: 'JSS1 English Test',
    academicLevelId: 'level-jss1',
    academicLevelName: 'JSS1',
    subjectName: 'English',
    curriculumSubjectId: 'subject-jss1-english',
    assessmentComponentId: 'component-test',
    assessmentName: 'TEST',
    questionCount: 20,
    durationMinutes: 45,
    selectionMode: 'random',
    status: 'draft',
    statusLabel: 'Draft',
    authoringVersion: 1,
    revisionNumber: 1,
    leadTeacherId: 'teacher-1',
    scheduledStartAt: null,
    createdAt: '2026-09-23T08:00:00Z',
    updatedAt: '2026-09-23T08:00:00Z',
    ...overrides,
  }
}

function teacherData(exams) {
  return {
    exams,
    assignments: [
      { teacherMembershipId: 'teacher-1', curriculumSubjectId: 'subject-jss1-english' },
      { teacherMembershipId: 'teacher-1', curriculumSubjectId: 'subject-jss2-math' },
    ],
    subjects: [
      {
        id: 'subject-jss1-english',
        academicLevelId: 'level-jss1',
        academicLevelName: 'JSS1',
        academicLevelCategory: 'junior_secondary',
        academicLevelPosition: 1,
        name: 'English',
        code: 'ENG',
      },
      {
        id: 'subject-jss2-math',
        academicLevelId: 'level-jss2',
        academicLevelName: 'JSS2',
        academicLevelCategory: 'junior_secondary',
        academicLevelPosition: 2,
        name: 'Mathematics',
        code: 'MTH',
      },
    ],
    assessmentComponents: [
      { id: 'component-test', name: 'TEST', maximumScore: 20 },
    ],
    loading: false,
    error: '',
    warning: '',
    refresh: vi.fn().mockResolvedValue(undefined),
  }
}

describe('exam workspace filter regressions', () => {
  it('keeps teacher exams visible when their academic level is selected', () => {
    const data = teacherData([
      exam(),
      exam({
        id: 'exam-2',
        title: 'JSS2 Mathematics Test',
        academicLevelId: 'level-jss2',
        academicLevelName: 'JSS2',
        subjectName: 'Mathematics',
        curriculumSubjectId: 'subject-jss2-math',
      }),
    ])

    render(
      <TeacherExamsPage
        state={state}
        dispatch={vi.fn()}
        teacherData={data}
        gateway={{ exams: {} }}
      />,
    )

    fireEvent.click(screen.getByRole('combobox', { name: 'Academic level filter' }))
    fireEvent.click(screen.getByRole('option', { name: 'JSS1' }))

    expect(screen.getByRole('button', { name: 'Open JSS1 English Test' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open JSS2 Mathematics Test' })).not.toBeInTheDocument()
  })

  it('prefers the real lifecycle timestamp over a fallback schedule date', () => {
    render(
      <ExamCard
        exam={exam({
          status: 'submitted',
          statusLabel: 'Submitted',
          submittedAt: '2026-09-23T14:30:00Z',
          scheduledStartAt: '2026-09-24T09:00:00Z',
        })}
        onOpen={vi.fn()}
      />,
    )

    expect(screen.getAllByText(/Submitted/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/Scheduled/)).not.toBeInTheDocument()
  })
})
