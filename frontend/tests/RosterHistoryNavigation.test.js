import { expect, it } from 'vitest'
import { parseStaffPath, pathForStaffState, staffSectionForRole } from '../src/app/staffNavigation'

it('maps the dedicated admin roster history route without exposing it to teachers', () => {
  expect(staffSectionForRole('admin', 'roster-history')).toBe('roster-history')
  expect(staffSectionForRole('teacher', 'roster-history')).toBe('overview')

  const route = parseStaffPath('/admin/roster-history')
  expect(route.staffSection).toBe('roster-history')
  expect(route.role).toBe('admin')

  expect(pathForStaffState({
    session: { role: 'admin' },
    staff: { section: 'roster-history' },
  })).toBe('/admin/roster-history')
})
