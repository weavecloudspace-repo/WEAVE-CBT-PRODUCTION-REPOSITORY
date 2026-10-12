import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionBuilder } from '../src/features/teacher/QuestionBuilder'

const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

const subject = {
  id: 'subject-1',
  academicLevelId: 'level-jss1',
  academicLevelName: 'JSS1',
  academicLevelCategory: 'junior_secondary',
  academicLevelPosition: 1,
  name: 'English Language',
  code: 'ENG',
}

const bank = {
  id: 'bank-1',
  curriculumSubjectId: subject.id,
  academicLevelId: subject.academicLevelId,
  academicLevelName: subject.academicLevelName,
  subjectName: subject.name,
  name: 'JSS1 ENGLISH',
  count: 0,
}

describe('QuestionBuilder local image feedback', () => {
  let createdUrls
  let revokedUrls

  beforeEach(() => {
    createdUrls = []
    revokedUrls = []
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => {
        const url = `blob:question-preview-${createdUrls.length + 1}`
        createdUrls.push(url)
        return url
      }),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn((url) => revokedUrls.push(url)),
    })
  })

  afterEach(() => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: originalRevokeObjectURL })
  })

  it('keeps committed prompt and option preview URLs valid in React Strict Mode', async () => {
    const { container } = render(
      <StrictMode>
        <QuestionBuilder
          state={{ staff: { selectedBankId: bank.id, selectedQuestionId: null } }}
          dispatch={vi.fn()}
          teacherData={{ subjects: [subject], banks: [bank], refresh: vi.fn() }}
          gateway={{ media: { uploadQuestionImage: vi.fn() }, questions: {} }}
        />
      </StrictMode>,
    )

    expect(screen.getByRole('combobox', { name: /academic level/i })).toHaveTextContent('JSS1')
    expect(screen.getByRole('combobox', { name: /^subject$/i })).toHaveTextContent('English Language')

    const [questionImageInput, optionImageInput] = container.querySelectorAll('input[type="file"]')
    const questionFile = new File(['question image bytes'], 'question.png', { type: 'image/png' })
    const optionFile = new File(['option image bytes'], 'option-a.png', { type: 'image/png' })
    fireEvent.change(questionImageInput, { target: { files: [questionFile] } })
    fireEvent.change(optionImageInput, { target: { files: [optionFile] } })

    const promptPreview = await screen.findByAltText('Question image preview')
    const optionPreview = await screen.findByAltText('Option A')
    await waitFor(() => {
      expect(promptPreview.getAttribute('src')).toMatch(/^blob:question-preview-/)
      expect(optionPreview.getAttribute('src')).toMatch(/^blob:question-preview-/)
    })

    const committedUrls = [promptPreview.getAttribute('src'), optionPreview.getAttribute('src')]
    committedUrls.forEach((url) => {
      expect(createdUrls).toContain(url)
      expect(revokedUrls).not.toContain(url)
    })
  })
})
