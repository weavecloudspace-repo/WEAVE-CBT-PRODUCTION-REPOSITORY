import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ExamDateTimePicker } from '../src/shared/exams/ExamDateTimePicker'
import { buildDestructiveQuestionConfigurationWarning } from '../src/shared/exams/ExamAuthoringPage'
import { ManualQuestionPicker } from '../src/shared/exams/ManualQuestionPicker'

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }
})

describe('Exam date and time picker', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T06:00:00'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('keeps changes pending until apply and preserves the local date/time value', () => {
    const onChange = vi.fn()
    render(<ExamDateTimePicker label="Scheduled start" value="2026-09-23T10:15" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Scheduled start' }))
    fireEvent.click(screen.getByRole('button', { name: /24.*September|September.*24/ }))
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('combobox', { name: 'Scheduled start hour' }))
    fireEvent.click(screen.getByRole('option', { name: '14' }))
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onChange).toHaveBeenCalledWith('2026-09-24T14:15')
  })

  it('blocks an earlier latest-start time and supports cancellation and clearing', () => {
    const onChange = vi.fn()
    render(<ExamDateTimePicker label="Latest normal start" value="2026-09-23T08:00" min="2026-09-23T09:00" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Normal entry deadline' }))
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /22.*September|September.*22/ })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Normal entry deadline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(onChange).toHaveBeenCalledWith('')
  })

  it('rejects an equal entry deadline, accepts the next minute, and allows clearing it', () => {
    const onChange = vi.fn()
    render(<ExamDateTimePicker label="Latest normal start" value="2026-09-23T08:00" min="2026-09-23T08:00" minExclusive onChange={onChange} />)
    expect(screen.getByRole('alert')).toHaveTextContent(/Equal times leave no time/)
    fireEvent.click(screen.getByRole('button', { name: 'Normal entry deadline' }))
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
    fireEvent.click(screen.getByRole('combobox', { name: 'Normal entry deadline minute' }))
    fireEvent.click(screen.getByRole('option', { name: '01' }))
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onChange).toHaveBeenCalledWith('2026-09-23T08:01')
    fireEvent.click(screen.getByRole('button', { name: 'Normal entry deadline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(onChange).toHaveBeenLastCalledWith('')
  })

  it('clearly flags an existing authoring time after it has elapsed', () => {
    render(<ExamDateTimePicker label="Scheduled start" value="2026-09-23T05:30" onChange={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent(/time has elapsed/i)
    expect(screen.getByRole('button', { name: 'Scheduled start' })).toHaveClass('is-overdue')
  })
})

const questions = [
  { id: 'q1', prompt: 'First question', question_type: 'single_choice', is_active: true, options: [] },
  { id: 'q2', prompt: 'Second question', question_type: 'single_choice', is_active: true, options: [] },
  { id: 'q3', prompt: 'Archived question', question_type: 'single_choice', is_active: false, options: [] },
]

describe('Manual question picker', () => {
  it('opens the full preview without changing the manual selection', async () => {
    const onPreview = vi.fn()
    const onChange = vi.fn()
    render(<ManualQuestionPicker bankId="bank" exam={{ questionCount: 1 }} selectedIds={['q1']} onChange={onChange} onPreview={onPreview} gateway={{ questions: { listQuestionsForBank: vi.fn().mockResolvedValue(questions) } }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Preview question: First question' }))
    expect(onPreview).toHaveBeenCalledWith('q1', expect.any(HTMLButtonElement))
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /Remove question from exam: First question/ })).toBeEnabled()
  })

  it('limits new selections to the requested count and excludes archived questions', async () => {
    const onChange = vi.fn()
    render(<ManualQuestionPicker bankId="bank" exam={{ questionCount: 1 }} selectedIds={['q1']} onChange={onChange} gateway={{ questions: { listQuestionsForBank: vi.fn().mockResolvedValue(questions) } }} />)
    expect(await screen.findByRole('button', { name: /Remove question from exam: First question/ })).toBeEnabled()
    expect(screen.getByRole('checkbox', { name: /Second question/ })).toBeDisabled()
    expect(screen.queryByRole('checkbox', { name: /Archived question/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Remove question from exam: First question/ }))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('loads saved selections and uses each returned authoring version for subsequent mutations', async () => {
    const removeManualQuestion = vi.fn().mockResolvedValue({ authoring_version: 8 })
    const addManualQuestions = vi.fn().mockResolvedValue({ authoring_version: 9 })
    const onSaved = vi.fn().mockResolvedValue(undefined)
    render(<ManualQuestionPicker bankId="bank" exam={{ id: 'exam', questionCount: 1 }} selectedIds={[]} canManageAllSelections onBusyChange={vi.fn()} onSaved={onSaved} gateway={{ questions: { listQuestionsForBank: vi.fn().mockResolvedValue(questions) }, exams: { getExam: vi.fn().mockResolvedValue({ authoring_version: 7 }), listManualQuestions: vi.fn().mockResolvedValue([{ question_id: 'q1' }]), removeManualQuestion, addManualQuestions } }} />)
    fireEvent.click(await screen.findByRole('button', { name: /Remove question from exam: First question/ }))
    await waitFor(() => expect(removeManualQuestion).toHaveBeenCalledWith('exam', 'q1', 7))
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /Second question/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('checkbox', { name: /Second question/ }))
    await waitFor(() => expect(addManualQuestions).toHaveBeenCalledWith('exam', ['q2'], 8))
    expect(onSaved).toHaveBeenCalledTimes(2)
  })
})

describe('Destructive question configuration warnings', () => {
  const selections = [
    { question_id: 'q1', added_by_actor_id: 'teacher-a' },
    { question_id: 'q2', added_by_actor_id: 'teacher-b' },
    { question_id: 'q3', added_by_actor_id: 'teacher-b' },
  ]

  it('explains the impact of switching a collaborative manual paper to random', () => {
    const message = buildDestructiveQuestionConfigurationWarning({ selections, changingToRandom: true })
    expect(message).toContain('Switch to Random Selection?')
    expect(message).toContain('3 manually selected questions from 2 contributors')
    expect(message).toContain('cannot be restored automatically')
  })

  it('explains why changing banks clears the current manual selection', () => {
    const message = buildDestructiveQuestionConfigurationWarning({ selections, changingBank: true })
    expect(message).toContain('Change Question Bank?')
    expect(message).toContain('belong to the current question bank')
  })
})
