import { ToastHost } from '../src/shared/ui/ToastHost'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AdminResultDetailPage, AdminResultsPage } from '../src/features/admin/pages/AdminResultsPage'

function makeSubject(overrides = {}) {
  return {
    id: 'jss2-math',
    academicLevelId: 'jss2',
    academicLevelName: 'JSS2',
    academicLevelCategory: 'junior_secondary',
    academicLevelPosition: 2,
    name: 'Mathematics',
    code: 'MTH',
    ...overrides,
  }
}

function makeExam(overrides = {}) {
  return {
    id: 'exam-1',
    title: 'Mathematics CA 1',
    academicLevelId: 'jss2',
    academicLevelName: 'JSS2',
    subjectName: 'Mathematics',
    subjectCode: 'MTH',
    curriculumSubjectId: 'jss2-math',
    assessmentName: 'CA 1',
    assessmentComponentId: 'component-1',
    componentMaximumScore: 10,
    status: 'closed',
    statusLabel: 'Closed',
    closedAt: '2026-09-18T10:45:00Z',
    cancelledAt: null,
    ...overrides,
  }
}

function makeAdminData(exams) {
  return {
    exams,
    subjects: [makeSubject()],
    loading: false,
    error: '',
    warning: '',
  }
}

function pendingReview(examId = 'exam-1', overrides = {}) {
  return {
    exam_id: examId,
    completed_at: '2026-09-18T10:45:00Z',
    result_disposition: 'pending_review',
    results_decided_at: null,
    results_decision_reason: null,
    result_count: 126,
    pending_count: 126,
    syncing_count: 0,
    synced_count: 0,
    failed_count: 0,
    ...overrides,
  }
}

function makeResult(overrides = {}) {
  return {
    id: 'result-1',
    attempt_id: 'attempt-1',
    candidate_id: 'candidate-1',
    exam_id: 'exam-1',
    assessment_component_id: 'component-1',
    candidate_display_name: 'David Obi',
    admission_number: 'JSS2/014',
    class_id: 'class-1',
    raw_score: 13,
    raw_max_score: 20,
    percentage: '65.00',
    component_score: '6.50',
    component_maximum_score: '10.00',
    calculated_at: '2026-09-18T10:45:00Z',
    sync_status: 'pending',
    sync_batch_id: null,
    sync_attempts: 0,
    last_sync_attempt_at: null,
    synced_at: null,
    sync_error: null,
    ...overrides,
  }
}

function makeGateway({ review = pendingReview(), control = null, results = [makeResult()] } = {}) {
  return {
    results: {
      listResultReviewSets: vi.fn().mockResolvedValue({ reviews: [review] }),
      getExamResultControl: vi.fn().mockResolvedValue(control || {
        exam_id: 'exam-1',
        operation: null,
        operation_source: null,
        operation_requested_at: null,
        operation_requested_by_actor_id: null,
        operation_reason: null,
        operation_attempts: 0,
        last_operation_attempt_at: null,
        operation_error: null,
        result_disposition: review.result_disposition,
        results_decided_at: review.results_decided_at,
        results_decided_by_actor_id: null,
        results_decision_reason: review.results_decision_reason,
      }),
      listExamResults: vi.fn().mockResolvedValue({
        exam_id: 'exam-1',
        offset: 0,
        limit: 50,
        total: results.length,
        results,
      }),
      approveExamResults: vi.fn().mockResolvedValue({ result_disposition: 'approved' }),
      voidExamResults: vi.fn().mockResolvedValue({ result_disposition: 'voided' }),
      voidResult: vi.fn().mockResolvedValue({}),
      retryExamResultSync: vi.fn().mockResolvedValue({ reset_count: 1, queued: true }),
    },
  }
}

describe('Admin result review workspace', () => {
  it('voids only the selected candidate with a reason, then refreshes the audit row', async () => {
    const gateway = makeGateway()
    render(<AdminResultDetailPage state={{ staff: { selectedExamId: 'exam-1' } }} adminData={makeAdminData([makeExam()])} gateway={gateway} onNavigate={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Void result' }))
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent('David Obi')
    expect(within(dialog).getByRole('button', { name: 'Void candidate result' })).toBeDisabled()
    gateway.results.listExamResults.mockResolvedValue({ total: 1, results: [makeResult({ voided_at: '2026-10-07T10:00:00Z', void_reason: 'Confirmed incident' })] })
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Confirmed incident' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Void candidate result' }))
    await waitFor(() => expect(gateway.results.voidResult).toHaveBeenCalledWith('result-1', 'Confirmed incident'))
    expect(gateway.results.voidExamResults).not.toHaveBeenCalled()
    expect(await screen.findByText('Confirmed incident')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Void result' })).not.toBeInTheDocument()
    expect(screen.getByText('13 / 20')).toBeInTheDocument()
  })

  it('disables individual void for uncertain or already delivered results', async () => {
    const gateway = makeGateway({ results: [makeResult({ sync_status: 'failed', sync_batch_id: 'uncertain-batch' }), makeResult({ id: 'result-2', sync_status: 'synced', sync_batch_id: 'sent-batch' })] })
    render(<AdminResultDetailPage state={{ staff: { selectedExamId: 'exam-1' } }} adminData={makeAdminData([makeExam()])} gateway={gateway} onNavigate={vi.fn()} />)
    const buttons = await screen.findAllByRole('button', { name: 'Void result' })
    buttons.forEach((button) => expect(button).toBeDisabled())
  })
  it('defaults to result sets awaiting review and opens the exact examination', async () => {
    const pendingExam = makeExam()
    const approvedExam = makeExam({ id: 'exam-2', title: 'English CA 1', curriculumSubjectId: 'jss2-english', subjectName: 'English Language' })
    const gateway = {
      results: {
        listResultReviewSets: vi.fn().mockResolvedValue({
          reviews: [
            pendingReview(),
            pendingReview('exam-2', { result_disposition: 'approved', pending_count: 0, synced_count: 119, result_count: 119 }),
          ],
        }),
      },
    }
    const onNavigate = vi.fn()

    render(<AdminResultsPage adminData={makeAdminData([pendingExam, approvedExam])} gateway={gateway} onNavigate={onNavigate} />)

    expect(await screen.findByText('Mathematics CA 1')).toBeInTheDocument()
    expect(screen.queryByText('English CA 1')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /review/i }))
    expect(onNavigate).toHaveBeenCalledWith('result-detail', { selectedExamId: 'exam-1' })
  })

  it('searches candidate results on the server by admission number and renders score representations', async () => {
    const exam = makeExam()
    const gateway = makeGateway()

    render(
      <AdminResultDetailPage
        state={{ staff: { selectedExamId: exam.id } }}
        adminData={makeAdminData([exam])}
        gateway={gateway}
        onNavigate={vi.fn()}
      />,
    )

    expect(await screen.findByText('David Obi')).toBeInTheDocument()
    expect(screen.getByText('JSS2/014')).toBeInTheDocument()
    expect(screen.getByText('13 / 20')).toBeInTheDocument()
    expect(screen.getByText('65%')).toBeInTheDocument()
    expect(screen.getByText('6.5 / 10')).toBeInTheDocument()

    fireEvent.change(screen.getByRole('searchbox', { name: /search candidate results/i }), {
      target: { value: 'JSS2/014' },
    })

    await waitFor(() => expect(gateway.results.listExamResults).toHaveBeenLastCalledWith('exam-1', {
      offset: 0,
      limit: 50,
      search: 'JSS2/014',
    }))
  })

  it('approves the entire selected examination result set through the real review action', async () => {
    const exam = makeExam()
    const gateway = makeGateway()

    render(
      <AdminResultDetailPage
        state={{ staff: { selectedExamId: exam.id } }}
        adminData={makeAdminData([exam])}
        gateway={gateway}
        onNavigate={vi.fn()}
      />,
    )

    await screen.findByText('David Obi')
    fireEvent.click(screen.getByRole('button', { name: /^approve results$/i }))

    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent(/authorizes these local cbt scores for synchronization to weave/i)
    fireEvent.click(within(dialog).getByRole('button', { name: /^approve results$/i }))

    await waitFor(() => expect(gateway.results.approveExamResults).toHaveBeenCalledWith('exam-1'))
  })

  it('requires an audit reason before voiding the whole result set', async () => {
    render(<ToastHost />)
    const exam = makeExam()
    const gateway = makeGateway()

    render(
      <AdminResultDetailPage
        state={{ staff: { selectedExamId: exam.id } }}
        adminData={makeAdminData([exam])}
        gateway={gateway}
        onNavigate={vi.fn()}
      />,
    )

    await screen.findByText('David Obi')
    fireEvent.click(screen.getByRole('button', { name: /void result set/i }))

    const dialog = screen.getByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^void result set$/i }))
    expect(await screen.findByText(/enter a reason before voiding/i)).toBeInTheDocument()
    expect(gateway.results.voidExamResults).not.toHaveBeenCalled()

    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Paper configuration was invalid' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /^void result set$/i }))

    await waitFor(() => expect(gateway.results.voidExamResults).toHaveBeenCalledWith('exam-1', 'Paper configuration was invalid'))
  })
})
