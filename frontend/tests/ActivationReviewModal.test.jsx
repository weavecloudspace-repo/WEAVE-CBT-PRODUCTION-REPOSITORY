import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ActivationReviewModal } from '../src/features/admin/components/ActivationReviewModal'

const future = (minutes) => new Date(Date.now() + minutes * 60_000).toISOString()
const clear = () => ({ can_activate: true, blockers: [], affected_exams: [] })
function impact(overrides = {}) {
  return {
    exam_id: 'later', title: 'Literature', status: 'sealed',
    scheduled_start_at: future(15), suggested_start_at: future(80),
    suggested_end_at: future(140), reason: 'Delayed by English',
    blocked_by_exam_ids: ['source'], ...overrides,
  }
}
function clash(overrides = {}) {
  return { can_activate: false, blockers: ['schedule_reschedule_required'], affected_exams: [impact()], suggestion_valid_until_at: future(5), ...overrides }
}
function setup(preflight = clear()) {
  const props = {
    exam: { id: 'source', title: 'English', status: 'sealed', rosterStatus: 'ready', scheduledStartAt: future(-30) },
    exams: [],
    gateway: { exams: {
      activationPreflight: vi.fn().mockResolvedValue(preflight),
      rescheduleActivationImpact: vi.fn().mockResolvedValue({ preflight: clear(), rescheduled_exam_ids: ['later'] }),
      activateExam: vi.fn().mockResolvedValue({}),
    } },
    onCancel: vi.fn(), onRefresh: vi.fn().mockResolvedValue(), onActivated: vi.fn(),
  }
  render(<ActivationReviewModal {...props} />)
  return props
}

describe('Activation timetable review', () => {
  it('shows the chain, saves suggested times atomically, then waits for explicit activation', async () => {
    const proposal = clash({ affected_exams: [impact(), impact({ exam_id: 'math', title: 'Mathematics', suggested_start_at: future(150) })] })
    const props = setup(proposal)
    await screen.findByText('2 affected sittings')
    const save = screen.getByRole('button', { name: 'Save affected timetable' })
    fireEvent.click(save)
    expect(await screen.findByText('Enter a reason for changing the affected timetable.')).toBeVisible()
    expect(props.gateway.exams.rescheduleActivationImpact).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Reason for timetable changes'), { target: { value: 'Late start after power outage' } })
    const local = screen.getByLabelText('New start for Literature').value
    const mathLocal = screen.getByLabelText('New start for Mathematics').value
    fireEvent.click(save)
    await screen.findByText(/The affected timetable is saved/)
    expect(props.gateway.exams.rescheduleActivationImpact).toHaveBeenCalledWith('source', [
      { exam_id: 'later', scheduled_start_at: new Date(local).toISOString() },
      { exam_id: 'math', scheduled_start_at: new Date(mathLocal).toISOString() },
    ], 'Late start after power outage')
    expect(props.gateway.exams.activateExam).not.toHaveBeenCalled()
    props.gateway.exams.activationPreflight.mockResolvedValue(clear())
    fireEvent.click(screen.getByRole('button', { name: 'Activate examination' }))
    await waitFor(() => expect(props.onActivated).toHaveBeenCalled())
  })

  it('accepts a custom local start and sends a timezone-aware UTC timestamp', async () => {
    const props = setup(clash())
    const input = await screen.findByLabelText('New start for Literature')
    const custom = '2099-10-07T16:30:45'
    fireEvent.change(input, { target: { value: custom } })
    fireEvent.change(screen.getByLabelText('Reason for timetable changes'), { target: { value: 'Centre requested a later sitting' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save affected timetable' }))
    await waitFor(() => expect(props.gateway.exams.rescheduleActivationImpact).toHaveBeenCalledWith('source', [{ exam_id: 'later', scheduled_start_at: new Date(custom).toISOString() }], 'Centre requested a later sitting'))
  })

  it('blocks expired suggestions until the administrator checks again', async () => {
    const props = setup(clash({ suggestion_valid_until_at: future(-1) }))
    await screen.findByText(/These suggestions have expired/)
    expect(screen.getByRole('button', { name: 'Save affected timetable' })).toBeDisabled()
    props.gateway.exams.activationPreflight.mockResolvedValue(clash())
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save affected timetable' })).toBeEnabled())
  })

  it('explains occupied candidates and does not offer timetable recovery', async () => {
    const props = setup(clash({ blockers: ['candidate_scope_conflict', 'schedule_reschedule_required'] }))
    await screen.findByText(/Candidates are already assigned/)
    expect(screen.getByRole('button', { name: 'Save affected timetable' })).toBeDisabled()
    expect(screen.queryByLabelText('New start for Literature')).not.toBeInTheDocument()
    expect(props.gateway.exams.activateExam).not.toHaveBeenCalled()
  })

  it('refreshes the actual chain after a rejected batch and keeps the reason', async () => {
    const props = setup(clash())
    await screen.findByLabelText('New start for Literature')
    props.gateway.exams.rescheduleActivationImpact.mockRejectedValue({ userMessage: 'The proposed timetable still conflicts.' })
    props.gateway.exams.activationPreflight.mockResolvedValue(clash({ affected_exams: [impact({ title: 'Updated Literature' })] }))
    fireEvent.change(screen.getByLabelText('Reason for timetable changes'), { target: { value: 'Power outage' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save affected timetable' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The proposed timetable still conflicts.')
    expect(screen.getByText('Updated Literature')).toBeVisible()
    expect(screen.getByLabelText('Reason for timetable changes')).toHaveValue('Power outage')
    expect(props.gateway.exams.activateExam).not.toHaveBeenCalled()
  })

  it('shows a newly introduced clash instead of activating from a stale clear check', async () => {
    const props = setup()
    const dialog = screen.getByRole('alertdialog')
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Activate examination' })).toBeEnabled())
    props.gateway.exams.activationPreflight.mockResolvedValue(clash())
    fireEvent.click(screen.getByRole('button', { name: 'Activate examination' }))
    await screen.findByText('Resolve timetable clashes')
    expect(props.gateway.exams.activateExam).not.toHaveBeenCalled()
  })

  it('shows unresolved operational blockers without fabricating safe times', async () => {
    setup(clash({ affected_exams: [impact({ suggested_start_at: null, suggested_end_at: null })] }))
    await screen.findByText(/A safe start cannot be calculated/)
    expect(screen.getByRole('button', { name: 'Save affected timetable' })).toBeDisabled()
  })
})
