import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AdminTimetablePage } from '../src/features/admin/pages/AdminTimetablePage'
import { parseStaffPath, pathForStaffState, staffPatchFromRoute } from '../src/app/staffNavigation'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-09-26T12:00:00'))
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }
})
afterEach(() => vi.useRealTimers())

function exam(id, overrides = {}) {
  return { id, title: id, termId: 'term', curriculumSubjectId: id, assessmentComponentId: 'ca', academicLevelId: 'l1', academicLevelName: 'JSS1', subjectName: 'English', assessmentName: 'CA', status: 'sealed', statusLabel: 'Sealed', durationMinutes: 45, scheduledStartAt: '2026-09-26T09:00:00Z', ...overrides }
}
function data(exams = []) {
  return { exams, subjects: [{ academicLevelId: 'l1', academicLevelName: 'JSS1', academicLevelPosition: 1 }, { academicLevelId: 'l2', academicLevelName: 'JSS2', academicLevelPosition: 2 }], loading: false, refresh: vi.fn().mockResolvedValue(undefined) }
}
it('lists only scheduled current revisions awaiting their start in chronological order', () => {
  render(<AdminTimetablePage levelId="l1" adminData={data([
    exam('Later', { scheduledStartAt: '2026-09-27T09:00:00Z' }),
    exam('Old revision', { curriculumSubjectId: 'revised', revisionNumber: 1 }),
    exam('Current revision', { curriculumSubjectId: 'revised', revisionNumber: 2, revisionOfExamId: 'Old revision' }),
    exam('Unscheduled', { scheduledStartAt: null }),
    exam('Cancelled', { status: 'cancelled' }),
    exam('Cancelling', { status: 'cancelling' }),
    exam('Closed', { status: 'closed' }),
    exam('Closing', { status: 'closing' }),
    exam('Active', { status: 'active' }),
    exam('Suspended', { status: 'suspended' }),
    exam('Invalid date', { scheduledStartAt: 'invalid' }),
    exam('Scheduled draft', { status: 'draft', statusLabel: 'Draft' }),
    exam('Scheduled submitted', { status: 'submitted', statusLabel: 'Submitted' }),
  ])} />)
  expect(screen.getAllByRole('heading', { level: 4 }).map((node) => node.textContent)).toEqual(['Current revision', 'Scheduled draft', 'Scheduled submitted'])
  expect(screen.getByText('Draft')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('3 scheduled exams on')
})
function TimetableHarness({ adminData }) {
  const [levelId, setLevelId] = useState(null)
  return <AdminTimetablePage adminData={adminData} levelId={levelId} onSelectLevel={setLevelId} />
}
it('opens calendar collections without mixing papers from different levels and returns to collections', () => {
  render(<TimetableHarness adminData={data([exam('First level paper'), exam('Second level paper', { academicLevelId: 'l2', academicLevelName: 'JSS2' })])} />)
  expect(screen.queryByRole('region', { name: 'Scheduled examinations' })).not.toBeInTheDocument()
  expect(screen.queryByText('First level paper')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Open JSS1 schedule' }))
  expect(screen.getByText('First level paper')).toBeInTheDocument()
  expect(screen.queryByText('Second level paper')).not.toBeInTheDocument()
  expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-09-26T09:00:00Z')
  fireEvent.click(screen.getByRole('button', { name: 'All level schedules' }))
  fireEvent.click(screen.getByRole('button', { name: 'Open JSS2 schedule' }))
  expect(screen.getByText('Second level paper')).toBeInTheDocument()
  expect(screen.queryByText('First level paper')).not.toBeInTheDocument()
})
it('shows zero pending exams and an empty schedule for a level with only closed exams', () => {
  render(<TimetableHarness adminData={data([exam('Completed paper', { academicLevelId: 'l2', status: 'closed' })])} />)
  expect(screen.getByRole('button', { name: 'Open JSS2 schedule' })).toHaveTextContent('0 scheduled exams')
  fireEvent.click(screen.getByRole('button', { name: 'Open JSS2 schedule' }))
  expect(screen.getByText('No scheduled examinations')).toBeInTheDocument()
})
it('distinguishes loading and failure from an empty timetable and retries', async () => {
  const adminData = data()
  const view = render(<AdminTimetablePage adminData={{ ...adminData, loading: true }} />)
  expect(screen.getByRole('status')).toHaveTextContent('Loading timetable')
  expect(screen.queryByText('No scheduled examinations')).not.toBeInTheDocument()
  view.rerender(<AdminTimetablePage adminData={{ ...adminData, warning: 'Schedule request failed.' }} />)
  expect(screen.getByText('Timetable unavailable')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  await waitFor(() => expect(adminData.refresh).toHaveBeenCalledOnce())
})
it('round-trips the administrator timetable URL without granting teachers the page', () => {
  expect(parseStaffPath('/admin/timetable').staffSection).toBe('timetable')
  expect(pathForStaffState({ session: { role: 'admin' }, staff: { section: 'timetable' } })).toBe('/admin/timetable')
  expect(parseStaffPath('/teacher/timetable').staffSection).toBe('overview')
})

it('restores a selected level from the timetable URL', () => {
  const route = parseStaffPath('/admin/timetable?level=l1')
  const staff = staffPatchFromRoute(route)
  expect(staff.timetableLevelId).toBe('l1')
  expect(pathForStaffState({ session: { role: 'admin' }, staff })).toBe('/admin/timetable?level=l1')
  expect(staffPatchFromRoute(parseStaffPath('/admin/timetable')).timetableLevelId).toBeNull()
})

it('defaults to today and lets users select past dates and return to today', () => {
  render(<TimetableHarness adminData={data([
    exam('Today paper'),
    exam('Past paper', { scheduledStartAt: '2026-09-24T09:00:00Z' }),
    exam('Future paper', { scheduledStartAt: '2026-09-29T09:00:00Z' }),
  ])} />)
  expect(screen.getByRole('button', { name: 'Open JSS1 schedule' })).toHaveTextContent('1 scheduled exam')
  fireEvent.click(screen.getByRole('button', { name: 'Open JSS1 schedule' }))
  expect(screen.getByText('Today paper')).toBeInTheDocument()
  expect(screen.queryByText('Past paper')).not.toBeInTheDocument()
  expect(screen.queryByText('Future paper')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Timetable date:/ }))
  fireEvent.click(screen.getByRole('button', { name: new Date('2026-09-24T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }) }))
  expect(screen.getByText('Past paper')).toBeInTheDocument()
  expect(screen.queryByText('Today paper')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'All level schedules' }))
  fireEvent.click(screen.getByRole('button', { name: 'Open JSS1 schedule' }))
  expect(screen.getByText('Past paper')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Timetable date:/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  expect(screen.getByText('Today paper')).toBeInTheDocument()
  expect(screen.queryByText('Past paper')).not.toBeInTheDocument()
})