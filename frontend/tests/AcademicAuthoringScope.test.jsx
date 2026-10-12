import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { QuestionBuilder } from '../src/features/teacher/QuestionBuilder'
import { buildAcademicLevels, listSubjectsForLevel } from '../src/shared/academics/authoringScope'

const subjects = [
  {
    id: 'jss1-math',
    academicLevelId: 'jss1',
    academicLevelName: 'JSS1',
    academicLevelCategory: 'junior_secondary',
    academicLevelPosition: 1,
    name: 'Mathematics',
    code: 'MTH',
  },
  {
    id: 'jss2-math',
    academicLevelId: 'jss2',
    academicLevelName: 'JSS2',
    academicLevelCategory: 'junior_secondary',
    academicLevelPosition: 2,
    name: 'Mathematics',
    code: 'MTH',
  },
  {
    id: 'jss2-science',
    academicLevelId: 'jss2',
    academicLevelName: 'JSS2',
    academicLevelCategory: 'junior_secondary',
    academicLevelPosition: 2,
    name: 'Basic Science',
    code: 'BSC',
  },
]

const banks = [
  {
    id: 'bank-jss1-math',
    curriculumSubjectId: 'jss1-math',
    academicLevelId: 'jss1',
    academicLevelName: 'JSS1',
    subjectName: 'Mathematics',
    name: 'JSS1 Mathematics Bank',
    count: 12,
  },
  {
    id: 'bank-jss2-math',
    curriculumSubjectId: 'jss2-math',
    academicLevelId: 'jss2',
    academicLevelName: 'JSS2',
    subjectName: 'Mathematics',
    name: 'JSS2 Mathematics Bank',
    count: 18,
  },
  {
    id: 'bank-jss2-science',
    curriculumSubjectId: 'jss2-science',
    academicLevelId: 'jss2',
    academicLevelName: 'JSS2',
    subjectName: 'Basic Science',
    name: 'JSS2 Science Bank',
    count: 14,
  },
]

describe('academic authoring scope', () => {
  it('builds stable level context without collapsing same-named subjects', () => {
    expect(buildAcademicLevels(subjects).map((level) => level.name)).toEqual(['JSS1', 'JSS2'])
    expect(listSubjectsForLevel(subjects, 'jss2').map((subject) => subject.id)).toEqual(['jss2-math', 'jss2-science'])
  })

  it('filters question subjects and banks when the academic level changes', () => {
    render(
      <QuestionBuilder
        state={{ staff: { selectedBankId: 'bank-jss1-math', selectedQuestionId: null } }}
        dispatch={vi.fn()}
        teacherData={{ subjects, banks, refresh: vi.fn() }}
        gateway={{ media: { uploadQuestionImage: vi.fn() }, questions: {} }}
      />,
    )

    const levelSelect = screen.getByRole('combobox', { name: /academic level/i })
    expect(levelSelect).toHaveTextContent('JSS1')
    expect(screen.getByRole('combobox', { name: /^subject$/i })).toHaveTextContent('Mathematics')
    expect(screen.getByRole('combobox', { name: /question bank/i })).toHaveTextContent('JSS1 Mathematics Bank')

    fireEvent.click(levelSelect)
    fireEvent.click(screen.getByRole('option', { name: /JSS2/i }))

    fireEvent.click(screen.getByRole('combobox', { name: /^subject$/i }))
    expect(screen.getByRole('option', { name: /Basic Science/i })).toBeInTheDocument()
    expect(screen.getAllByRole('option', { name: /Mathematics/i })).toHaveLength(1)
    fireEvent.click(screen.getByRole('option', { name: /Basic Science/i }))

    expect(screen.getByRole('combobox', { name: /question bank/i })).toHaveTextContent('JSS2 Science Bank')
    fireEvent.click(screen.getByRole('combobox', { name: /question bank/i }))
    expect(screen.getByRole('option', { name: /JSS2 Science Bank/i })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /JSS1 Mathematics Bank/i })).not.toBeInTheDocument()
  })
})
