import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { BulkExamOperations } from '../src/features/admin/components/BulkExamOperations'

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
})
function exam(id, status = 'sealed', overrides = {}) {
  return { id, title: `Exam ${id}`, status, rosterStatus: 'ready', scheduledStartAt: new Date(Date.now() - 600_000).toISOString(), ...overrides }
}
function setup(exams = [exam('one'), exam('two'), exam('stale', 'sealed', { rosterStatus: 'stale' })]) {
  const props = {
    exams, scopeKey: 'today', onRefresh: vi.fn().mockResolvedValue(), onOpen: vi.fn(),
    gateway: { exams: { batchExamOperation: vi.fn().mockResolvedValue({ results: exams.map((item) => ({ exam_id: item.id, succeeded: true, status: 'active' })) }) } },
    children: ({ operation, selectedIds, canSelect, toggle }) => <div>{exams.map((item) => <div key={item.id}>{item.title}{operation && <input type="checkbox" aria-label={`Select ${item.title}`} disabled={!canSelect(item)} checked={selectedIds.has(item.id)} onChange={() => toggle(item)} />}</div>)}</div>,
  }
  const rendered = render(<BulkExamOperations {...props} />)
  return { props, ...rendered }
}
function choose(label) {
  fireEvent.click(screen.getByRole('button', { name: 'Bulk operations' }))
  fireEvent.click(screen.getByRole('menuitem', { name: new RegExp(`^${label} examinations`) }))
}
function reviewAll() {
  fireEvent.click(screen.getByRole('button', { name: 'Select all eligible' }))
  fireEvent.click(screen.getByRole('button', { name: /^Continue/ }))
  return screen.getByRole('dialog')
}

describe('Bulk exam operations', () => {
  it('selects only due exams with ready rosters and performs one batch request', async () => {
    const { props } = setup()
    choose('Activate')
    expect(screen.getByLabelText('Select Exam stale')).toBeDisabled()
    const dialog = reviewAll()
    expect(dialog).toHaveTextContent('Activate 2 examinations?')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Activate selected examinations' }))
    await screen.findByText('Operation results')
    expect(props.gateway.exams.batchExamOperation).toHaveBeenCalledWith('activate', ['one', 'two'], undefined)
    expect(props.onRefresh).toHaveBeenCalledWith({ silent: false })
    expect(screen.getByText('2 succeeded · 0 need review')).toBeVisible()
  })

  it('requires a reason once and passes it to suspension of all selected active exams', async () => {
    const { props } = setup([exam('one', 'active'), exam('two', 'active'), exam('paused', 'suspended')])
    choose('Suspend')
    expect(screen.getByLabelText('Select Exam paused')).toBeDisabled()
    const dialog = reviewAll()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Suspend selected examinations' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter an audit reason')
    expect(props.gateway.exams.batchExamOperation).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: ' Power outage ' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Suspend selected examinations' }))
    await waitFor(() => expect(props.gateway.exams.batchExamOperation).toHaveBeenCalledWith('suspend', ['one', 'two'], 'Power outage'))
  })

  it('retains only failed exams and offers direct review after partial success', async () => {
    const { props } = setup([exam('one'), exam('two')])
    props.gateway.exams.batchExamOperation.mockResolvedValue({ results: [
      { exam_id: 'one', succeeded: true, status: 'active' },
      { exam_id: 'two', succeeded: false, error: 'Timetable clash' },
    ] })
    choose('Activate')
    const dialog = reviewAll()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Activate selected examinations' }))
    await screen.findByText('Timetable clash')
    fireEvent.click(screen.getByRole('button', { name: 'Review sitting' }))
    expect(props.onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 'two' }))
    expect(screen.getByLabelText('Select Exam one')).not.toBeChecked()
    expect(screen.getByLabelText('Select Exam two')).toBeChecked()
  })

  it('clears selections when filters change, including when returning to the original view', () => {
    const { props, rerender } = setup()
    choose('Activate')
    fireEvent.click(screen.getByRole('button', { name: 'Select all eligible' }))
    rerender(<BulkExamOperations {...props} scopeKey="filtered" />)
    expect(screen.getByLabelText('Select Exam one')).not.toBeChecked()
    rerender(<BulkExamOperations {...props} scopeKey="today" />)
    expect(screen.getByLabelText('Select Exam one')).not.toBeChecked()
  })

  it('does not offer activation for future sittings or repeat a batch while it is running', async () => {
    const { props } = setup([exam('one'), exam('future', 'sealed', { scheduledStartAt: '2099-10-07T12:00:00Z' })])
    let finish
    props.gateway.exams.batchExamOperation.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    choose('Activate')
    expect(screen.getByLabelText('Select Exam future')).toBeDisabled()
    const dialog = reviewAll()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Activate selected examinations' }))
    expect(within(dialog).getByRole('button', { name: 'Applying…' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: 'Go back' })).toBeDisabled()
    finish({ results: [{ exam_id: 'one', succeeded: true, status: 'active' }] })
    await screen.findByText('Operation results')
    expect(props.gateway.exams.batchExamOperation).toHaveBeenCalledTimes(1)
  })

  it('keeps terminal finalization distinct from completion and displays queue recovery warnings', async () => {
    const { props } = setup([exam('one', 'active')])
    props.gateway.exams.batchExamOperation.mockResolvedValue({ results: [{ exam_id: 'one', succeeded: true, status: 'closing', warning: 'Recovery worker will retry finalization.' }] })
    choose('Close')
    const dialog = reviewAll()
    expect(dialog).toHaveTextContent('This is permanent')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close selected examinations' }))
    expect(await screen.findByText(/Requested · finalization in progress/)).toHaveTextContent('Recovery worker will retry finalization.')
  })

  it('chunks large selections without dropping any selected exams', async () => {
    const exams = Array.from({ length: 101 }, (_, index) => exam(String(index), 'suspended'))
    const { props } = setup(exams)
    props.gateway.exams.batchExamOperation.mockImplementation(async (_operation, ids) => ({ results: ids.map((id) => ({ exam_id: id, succeeded: true, status: 'active' })) }))
    choose('Resume')
    const dialog = reviewAll()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Resume selected examinations' }))
    await screen.findByText('101 succeeded · 0 need review')
    expect(props.gateway.exams.batchExamOperation).toHaveBeenCalledTimes(2)
    expect(props.gateway.exams.batchExamOperation.mock.calls[0][1]).toHaveLength(100)
    expect(props.gateway.exams.batchExamOperation.mock.calls[1][1]).toEqual(['100'])
  })
})
