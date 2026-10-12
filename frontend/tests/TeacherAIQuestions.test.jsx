import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { TeacherAIComposer } from '../src/features/teacher/TeacherAIComposer'
import { TeacherAIReviewPage } from '../src/features/teacher/TeacherAIReviewPage'
import { TeacherAIQuota } from '../src/features/teacher/TeacherAIQuota'
import { AdminWorkspace } from '../src/features/admin/AdminWorkspace'
import { isQuotaExhausted } from '../src/features/teacher/teacherAI'
import { parseStaffPath, pathForStaffState, staffPatchFromRoute } from '../src/app/staffNavigation'

const { rows } = vi.hoisted(() => ({ rows: new Map() }))
vi.mock('../src/features/admin/useAdminData', () => ({
  useAdminData: () => ({ banks: [{ id: 'bank-1', name: 'Mathematics · JSS 1', status: 'Ready', curriculumSubjectId: 'math' }], subjects: [{ id: 'math', name: 'Mathematics', academicLevelId: 'jss1', academicLevelName: 'JSS 1' }], questions: [], exams: [], refresh: vi.fn() }),
}))
vi.mock('../src/features/questions/questionAIController', async (importOriginal) => ({
  ...await importOriginal(),
  createQuestionAIDraftStore: ({ scope }) => ({
    put: async (row) => rows.set(`${scope}:${row.draft_id}`, structuredClone(row)),
    get: async (id) => structuredClone(rows.get(`${scope}:${id}`)),
    delete: async (id) => rows.delete(`${scope}:${id}`),
    list: async () => [...rows.entries()].filter(([key]) => key.startsWith(`${scope}:`)).map(([, row]) => structuredClone(row)),
  }),
}))
const question = { question_type: 'single_choice', prompt: 'What is half of ten?', options: [{ text: 'Five', is_correct: true }, { text: 'Two', is_correct: false }] }
const bank = { id: 'bank-1', name: 'Mathematics · JSS 1' }
const state = { session: { actor: { id: 'teacher-1' }, role: 'teacher' }, staff: { section: 'review-ai-questions', selectedAIDraftId: 'draft-1' } }
const balance = { actor_type: 'teacher', total_available_credits: 12, weekly: { available_credits: 10, used_credits: 10, credit_limit: 20, reserved_credits: 0 }, extra: { available_credits: 2, reserved_credits: 0 } }
const exhausted = { ...balance, total_available_credits: 0, weekly: { ...balance.weekly, available_credits: 0 }, extra: { ...balance.extra, available_credits: 0 } }
const draft = { draft_id: 'draft-1', bank_id: bank.id, status: 'review', questions: [question, { ...question, prompt: 'Another question?' }], generation_request: { generation_prompt: 'Fractions in everyday life', difficulty: 'medium', visual_mode: 'auto' }, updated_at: '2026-10-01T10:00:00Z' }
function makeGateway() {
  return {
    ai: { getMyAIQuota: vi.fn().mockResolvedValue(balance), listMyAIQuotaRequests: vi.fn().mockResolvedValue({ items: [], total: 0 }), requestAICredits: vi.fn().mockResolvedValue({}) },
    questions: {
      generateAIQuestionDrafts: vi.fn(async (_bank, input) => ({ operation_id: input.operation_id, questions: [question], charge: { credits_charged: 1 } })),
      saveAIQuestionDrafts: vi.fn().mockResolvedValue({ questions: [question] }),
      regenerateAIQuestionDraft: vi.fn(async (_bank, input) => ({ operation_id: input.operation_id, question: { ...question, prompt: 'A new question?' }, charge: { credits_charged: 1 } })),
    },
  }
}
beforeAll(() => { Element.prototype.scrollIntoView = vi.fn() })
beforeEach(() => rows.clear())
afterEach(cleanup)

describe('Teacher AI authoring', () => {

  it('renders the same review content and controls in the administrator workspace', async () => {
    rows.set('teacher-1:draft-1', structuredClone(draft))
    rows.set('admin-1:draft-1', structuredClone(draft))
    const teacher = render(<TeacherAIReviewPage state={state} gateway={makeGateway()} dispatch={vi.fn()} teacherData={{ banks: [bank], refresh: vi.fn() }} />)
    await screen.findByRole('heading', { name: question.prompt })
    const teacherMarkup = teacher.container.querySelector('.teacher-ai-review').innerHTML
    cleanup()
    const adminState = { ...state, session: { role: 'admin', actor: { id: 'admin-1' } } }
    const admin = render(<AdminWorkspace state={adminState} gateway={makeGateway()} dispatch={vi.fn()} signOut={vi.fn()} />)
    await screen.findByRole('heading', { name: question.prompt })
    expect(admin.container.querySelector('.teacher-ai-review').innerHTML).toBe(teacherMarkup)
    expect(screen.getByRole('button', { name: 'Add all (2)' })).toBeEnabled()
  })

  it('gives administrators the same authoring layout and generator with credit management', async () => {
    const gateway = makeGateway()
    gateway.ai.getMyAIQuota.mockResolvedValue({ ...balance, actor_type: 'tenant_admin' })
    const dispatch = vi.fn()
    const adminState = { ...state, session: { role: 'admin', actor: { id: 'admin-1' } }, staff: { section: 'create-question', selectedBankId: bank.id } }
    const { container } = render(<AdminWorkspace state={adminState} gateway={gateway} dispatch={dispatch} signOut={vi.fn()} />)
    expect(container.querySelector('.admin-shell')).toHaveClass('teacher-shell--authoring')
    fireEvent.click(screen.getByRole('button', { name: 'Open question generation' }))
    const quotaSummary = await screen.findByLabelText('12 AI credits available')
    fireEvent.click(quotaSummary)
    expect(screen.getByRole('button', { name: 'Manage AI credits' })).toBeInTheDocument()
    expect(gateway.ai.listMyAIQuotaRequests).not.toHaveBeenCalled()
    fireEvent.click(quotaSummary)
    fireEvent.change(screen.getByLabelText('Describe questions to generate'), { target: { value: 'Fractions' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Generate questions' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Generate questions' }))
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: 'staff', patch: expect.objectContaining({ section: 'review-ai-questions' }) })))
    expect(gateway.questions.generateAIQuestionDrafts).toHaveBeenCalledWith('bank-1', expect.objectContaining({ generation_prompt: 'Fractions', question_count: 5 }))
    expect([...rows.keys()].some((key) => key.startsWith('admin-1:'))).toBe(true)
  })

  it('dismisses credit usage with Escape or an outside click', async () => {
    render(<TeacherAIComposer bank={bank} state={state} gateway={makeGateway()} dispatch={vi.fn()} />)
    const summary = await screen.findByLabelText('12 AI credits available')
    const popup = summary.closest('details')
    fireEvent.click(summary)
    expect(popup.open).toBe(true)
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Refresh AI credits' }))
    expect(popup.open).toBe(true)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(popup.open).toBe(false)
    expect(summary).toHaveFocus()
    fireEvent.click(summary)
    expect(popup.open).toBe(true)
    fireEvent.pointerDown(screen.getByLabelText('Describe questions to generate'))
    expect(popup.open).toBe(false)
  })

  it('configures generation through the popover and preserves selections after dismissal', async () => {
    const gateway = makeGateway()
    render(<TeacherAIComposer bank={bank} state={state} gateway={gateway} dispatch={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: 'Generation options: 5 questions, medium difficulty' })
    expect(screen.queryByRole('dialog', { name: 'Generation options' })).not.toBeInTheDocument()
    fireEvent.click(trigger)
    expect(screen.getByRole('slider', { name: 'Difficulty' })).toHaveFocus()
    fireEvent.change(screen.getByRole('slider', { name: 'Difficulty' }), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Question count'), { target: { value: '8' } })
    fireEvent.click(screen.getByRole('combobox', { name: 'Answer type' }))
    fireEvent.click(screen.getByRole('option', { name: 'Mixed' }))
    fireEvent.click(screen.getByRole('combobox', { name: 'Question format' }))
    fireEvent.click(screen.getByRole('option', { name: 'Text only' }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(trigger).toHaveFocus()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(trigger).toHaveAccessibleName('Generation options: 8 questions, difficult difficulty')
    fireEvent.click(trigger)
    expect(screen.getByLabelText('Question count')).toHaveValue(8)
    fireEvent.pointerDown(screen.getByLabelText('Describe questions to generate'))
    expect(screen.queryByRole('dialog', { name: 'Generation options' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Describe questions to generate'), { target: { value: 'Fractions' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Generate questions' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Generate questions' }))
    await waitFor(() => expect(gateway.questions.generateAIQuestionDrafts).toHaveBeenCalledWith('bank-1', expect.objectContaining({ question_count: 8, difficulty: 'difficult', visual_mode: 'text_only', question_type_counts: { single_choice: 4, multiple_choice: 4 } })))
  })

  it('allows clearing and typing a multi-digit question count without clamping keystrokes', async () => {
    const gateway = makeGateway()
    render(<TeacherAIComposer bank={bank} state={state} gateway={gateway} dispatch={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Generation options: 5 questions, medium difficulty' }))
    const input = screen.getByLabelText('Question count')
    fireEvent.change(input, { target: { value: '' } })
    expect(input).toHaveValue(null)
    fireEvent.change(input, { target: { value: '1' } })
    expect(input).toHaveValue(1)
    fireEvent.change(input, { target: { value: '10' } })
    expect(input).toHaveValue(10)
    fireEvent.blur(input)
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.change(screen.getByLabelText('Describe questions to generate'), { target: { value: 'Fractions' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Generate questions' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Generate questions' }))
    await waitFor(() => expect(gateway.questions.generateAIQuestionDrafts).toHaveBeenCalledWith('bank-1', expect.objectContaining({ question_count: 10 })))
  })

  it('rejects an invalid count even when the settings popup has closed', async () => {
    const gateway = makeGateway()
    render(<TeacherAIComposer bank={bank} state={state} gateway={gateway} dispatch={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Generation options: 5 questions, medium difficulty' }))
    fireEvent.change(screen.getByLabelText('Question count'), { target: { value: '51' } })
    expect(screen.getByLabelText('Question count')).toHaveValue(51)
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.change(screen.getByLabelText('Describe questions to generate'), { target: { value: 'Fractions' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Generate questions' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Generate questions' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a whole number of questions between 1 and 50.')
    expect(screen.getByLabelText('Describe questions to generate')).toHaveValue('Fractions')
    expect(gateway.questions.generateAIQuestionDrafts).not.toHaveBeenCalled()
  })

  it('resets generation settings to the defaults', async () => {
    render(<TeacherAIComposer bank={bank} state={state} gateway={makeGateway()} dispatch={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Generation options: 5 questions, medium difficulty' }))
    fireEvent.change(screen.getByLabelText('Question count'), { target: { value: '20' } })
    fireEvent.change(screen.getByRole('slider', { name: 'Difficulty' }), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('combobox', { name: 'Answer type' }))
    fireEvent.click(screen.getByRole('option', { name: 'Multiple choice' }))
    fireEvent.click(screen.getByRole('combobox', { name: 'Question format' }))
    fireEvent.click(screen.getByRole('option', { name: 'Text only' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reset generation options' }))
    expect(screen.getByLabelText('Question count')).toHaveValue(5)
    expect(screen.getByRole('slider', { name: 'Difficulty' })).toHaveValue('1')
    expect(screen.getByRole('combobox', { name: 'Answer type' })).toHaveTextContent('Single choice')
    expect(screen.getByRole('combobox', { name: 'Question format' })).toHaveTextContent('Text only')
    await screen.findByLabelText('12 AI credits available')
  })

  it('uses the selected bank and minimal prompt, opens review without saving', async () => {
    const gateway = makeGateway()
    const dispatch = vi.fn()
    render(<TeacherAIComposer bank={bank} state={state} gateway={gateway} dispatch={dispatch} />)
    fireEvent.change(screen.getByLabelText('Describe questions to generate'), { target: { value: 'Fractions in everyday life' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Generate questions' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Generate questions' }))
    expect(screen.getByLabelText('Describe questions to generate')).toHaveValue('')
    expect(screen.getByText('Fractions in everyday life')).toBeInTheDocument()
    await waitFor(() => expect(dispatch).toHaveBeenCalled())
    expect(gateway.questions.generateAIQuestionDrafts).toHaveBeenCalledWith('bank-1', expect.objectContaining({ generation_prompt: 'Fractions in everyday life', question_count: 5, question_type_counts: { single_choice: 5 } }))
    expect(gateway.questions.saveAIQuestionDrafts).not.toHaveBeenCalled()
    expect(dispatch.mock.calls[0][0].patch.section).toBe('review-ai-questions')
  })

  it('reviews, edits, removes, then adds only the final questions', async () => {
    rows.set('teacher-1:draft-1', structuredClone(draft))
    const gateway = makeGateway()
    const dispatch = vi.fn()
    render(<TeacherAIReviewPage state={state} gateway={gateway} dispatch={dispatch} teacherData={{ banks: [bank], refresh: vi.fn() }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Edit question 1' }))
    fireEvent.change(screen.getByLabelText('Question prompt'), { target: { value: 'Edited question?' } })
    expect(screen.getByRole('button', { name: 'Add all (2)' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Keep changes' }))
    await screen.findByRole('heading', { name: 'Edited question?' })
    fireEvent.click(screen.getByRole('button', { name: 'Next', exact: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete question 2' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove question' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add all (1)' })).toBeEnabled())
    expect(gateway.questions.saveAIQuestionDrafts).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Add all (1)' }))
    await waitFor(() => expect(gateway.questions.saveAIQuestionDrafts).toHaveBeenCalledWith('bank-1', { draft_id: 'draft-1', questions: [{ ...question, prompt: 'Edited question?' }] }))
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'staff', patch: { section: 'bank-detail', selectedBankId: bank.id, selectedAIDraftId: null } }))
  })

  it('reviews one question at a time and returns from preview to the same question', async () => {
    rows.set('teacher-1:draft-1', structuredClone(draft))
    render(<TeacherAIReviewPage state={state} gateway={makeGateway()} dispatch={vi.fn()} teacherData={{ banks: [bank], refresh: vi.fn() }} />)
    await screen.findByRole('heading', { name: question.prompt })
    expect(screen.queryByRole('heading', { name: 'Another question?' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Back', exact: true })).toBeDisabled()
    expect(screen.queryByText('Credits charged')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('AI credit usage')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next', exact: true }))
    expect(screen.getByRole('heading', { name: 'Another question?' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: question.prompt })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Preview', exact: true }))
    expect(screen.getByLabelText('Student question preview')).toBeInTheDocument()
    expect(screen.queryByText('Correct')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Back to review' }))
    expect(screen.getByRole('heading', { name: 'Another question?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Edit question 2' }))
    expect(screen.getByRole('button', { name: 'Back', exact: true })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Preview', exact: true })).toBeDisabled()
  })

  it('locks an uncertain save and retries the identical payload', async () => {
    rows.set('teacher-1:draft-1', structuredClone(draft))
    const gateway = makeGateway()
    gateway.questions.saveAIQuestionDrafts.mockRejectedValueOnce(new Error('Connection lost'))
    render(<TeacherAIReviewPage state={state} gateway={gateway} dispatch={vi.fn()} teacherData={{ banks: [bank], refresh: vi.fn() }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add all (2)' }))
    await screen.findByText('Connection lost')
    expect(screen.getByRole('button', { name: 'Edit question 1' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry Add all' }))
    await waitFor(() => expect(gateway.questions.saveAIQuestionDrafts).toHaveBeenCalledTimes(2))
    expect(gateway.questions.saveAIQuestionDrafts.mock.calls[0]).toEqual(gateway.questions.saveAIQuestionDrafts.mock.calls[1])
  })

  it('allows repeated regeneration of the same and different questions without credit-request lookups', async () => {
    rows.set('teacher-1:draft-1', structuredClone(draft))
    const gateway = makeGateway()
    gateway.ai.listMyAIQuotaRequests.mockRejectedValue(new Error('Request history unavailable'))
    render(<TeacherAIReviewPage state={state} gateway={gateway} dispatch={vi.fn()} teacherData={{ banks: [bank], refresh: vi.fn() }} />)
    const first = await screen.findByRole('button', { name: 'Regenerate question 1' })
    fireEvent.click(first)
    expect(first).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(first)
    expect(screen.queryByLabelText('What should change?')).not.toBeInTheDocument()
    for (const index of [1, 1, 2]) {
      if (index === 2) fireEvent.click(screen.getByRole('button', { name: 'Next', exact: true }))
      fireEvent.click(screen.getByRole('button', { name: `Regenerate question ${index}` }))
      fireEvent.change(screen.getByLabelText('What should change?'), { target: { value: 'Use another example' } })
      const submit = screen.getByRole('button', { name: 'Regenerate', exact: true })
      await waitFor(() => expect(submit).toBeEnabled())
      fireEvent.click(submit)
      await waitFor(() => expect(screen.queryByLabelText('What should change?')).not.toBeInTheDocument())
    }
    expect(gateway.questions.regenerateAIQuestionDraft).toHaveBeenCalledTimes(3)
    const ids = gateway.questions.regenerateAIQuestionDraft.mock.calls.map(([, payload]) => payload.operation_id)
    expect(new Set(ids).size).toBe(3)
    expect(gateway.ai.listMyAIQuotaRequests).not.toHaveBeenCalled()
  })

  it('lets a teacher retry a failed credit check before regeneration', async () => {
    rows.set('teacher-1:draft-1', structuredClone(draft))
    const gateway = makeGateway()
    gateway.ai.getMyAIQuota.mockRejectedValueOnce(new Error('Offline'))
    render(<TeacherAIReviewPage state={state} gateway={gateway} dispatch={vi.fn()} teacherData={{ banks: [bank], refresh: vi.fn() }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate question 1' }))
    fireEvent.change(screen.getByLabelText('What should change?'), { target: { value: 'Try another example' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Retry credit check' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Regenerate', exact: true })).toBeEnabled())
  })

  it('recovers a failed regeneration using its original operation ID', async () => {
    rows.set('teacher-1:draft-1', structuredClone(draft))
    const gateway = makeGateway()
    gateway.questions.regenerateAIQuestionDraft.mockRejectedValueOnce(new Error('Connection lost'))
    render(<TeacherAIReviewPage state={state} gateway={gateway} dispatch={vi.fn()} teacherData={{ banks: [bank], refresh: vi.fn() }} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Regenerate question 1' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate question 1' }))
    fireEvent.change(screen.getByLabelText('What should change?'), { target: { value: 'Use a shopping example' } })
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate', exact: true }))
    await screen.findByText('Connection lost')
    expect(screen.getByRole('button', { name: 'Add all (2)' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry regeneration' }))
    await screen.findByRole('heading', { name: 'A new question?' })
    expect(gateway.questions.regenerateAIQuestionDraft.mock.calls[0]).toEqual(gateway.questions.regenerateAIQuestionDraft.mock.calls[1])
  })

  it('does not expose another teacher’s browser drafts', async () => {
    rows.set('other-teacher:draft-1', structuredClone(draft))
    render(<TeacherAIReviewPage state={state} gateway={makeGateway()} dispatch={vi.fn()} teacherData={{ banks: [bank] }} />)
    await screen.findByRole('heading', { name: 'Draft not available' })
    expect(screen.queryByText(question.prompt)).not.toBeInTheDocument()
  })
})

describe('Teacher AI quota and routing', () => {
  it('requires zero weekly, extra, and reserved credits before offering a request', () => {
    expect(isQuotaExhausted(exhausted)).toBe(true)
    expect(isQuotaExhausted(balance)).toBe(false)
    expect(isQuotaExhausted(null)).toBe(false)
    expect(isQuotaExhausted({ ...exhausted, weekly: { ...exhausted.weekly, reserved_credits: 2 } })).toBe(false)
    expect(isQuotaExhausted({ ...exhausted, extra: { ...exhausted.extra, reserved_credits: 1 } })).toBe(false)
  })
  it('hides requests for pending or reserved credits and rechecks before sending', async () => {
    const api = makeGateway().ai
    const refresh = vi.fn().mockResolvedValue({ quota: balance, requests: [] })
    const model = { quota: exhausted, requests: [], exhausted: true, loading: false, refresh }
    const { rerender } = render(<TeacherAIQuota api={api} model={{ ...model, requests: [{ requested_credits: 20 }] }} />)
    expect(screen.queryByRole('button', { name: 'Request more credits' })).not.toBeInTheDocument()
    rerender(<TeacherAIQuota api={api} model={model} />)
    fireEvent.click(screen.getByRole('button', { name: 'Request more credits' }))
    fireEvent.click(screen.getByRole('button', { name: 'Send request' }))
    await waitFor(() => expect(refresh).toHaveBeenCalled())
    expect(api.requestAICredits).not.toHaveBeenCalled()
  })
  it('restores draft routes for teachers and admins', () => {
    const path = pathForStaffState(state)
    expect(path).toBe('/teacher/review-ai-questions?draft=draft-1')
    expect(staffPatchFromRoute(parseStaffPath(path)).selectedAIDraftId).toBe('draft-1')
    const adminPath = pathForStaffState({ ...state, session: { ...state.session, role: 'admin' } })
    expect(adminPath).toBe('/admin/review-ai-questions?draft=draft-1')
    expect(parseStaffPath(adminPath)).toMatchObject({ staffSection: 'review-ai-questions', selectedAIDraftId: 'draft-1' })
  })
})
