import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/* global process */

const frontendRoot = process.cwd()
const srcRoot = resolve(frontendRoot, 'src')

const forbiddenLegacyDirectories = ['components', 'lib', 'services', 'state']
const allowedTopLevelEntries = new Set([
  'ARCHITECTURE.md',
  'App.jsx',
  'api',
  'app',
  'assets',
  'features',
  'main.jsx',
  'shared',
  'styles',
])

describe('frontend architecture', () => {
  it('does not recreate legacy generic source buckets', () => {
    for (const directory of forbiddenLegacyDirectories) {
      expect(existsSync(`${srcRoot}/${directory}`), directory).toBe(false)
    }
  })

  it('keeps source ownership inside the documented top-level boundaries', () => {
    const unexpected = readdirSync(srcRoot).filter((entry) => !allowedTopLevelEntries.has(entry) && readdirSync(resolve(srcRoot, entry)).length > 0)
    expect(unexpected).toEqual([])
  })

  it('keeps staff and student application roots isolated', () => {
    const staffApp = readFileSync(resolve(srcRoot, 'app/StaffApp.jsx'), 'utf8')
    const studentApp = readFileSync(resolve(srcRoot, 'app/StudentApp.jsx'), 'utf8')
    const studentGateway = readFileSync(resolve(srcRoot, 'app/studentGateway.js'), 'utf8')

    expect(staffApp).not.toContain('StudentLoginPage')
    expect(staffApp).not.toContain('StudentWorkspace')

    expect(studentApp).not.toContain('StaffLoginPage')
    expect(studentApp).not.toContain('TeacherWorkspace')
    expect(studentApp).not.toContain('AdminWorkspace')
    expect(studentApp).not.toContain('SetupFlow')

    expect(studentGateway).not.toContain("../api/questions")
    expect(studentGateway).not.toContain("../api/exams")
    expect(studentGateway).not.toContain("../api/results")
    expect(studentGateway).not.toContain("../api/staffAuth")
    expect(studentGateway).not.toContain("../api/staffAttempts")
  })

  it('keeps separate Vite roots and ports for staff and student applications', () => {
    expect(existsSync(resolve(frontendRoot, 'apps/staff/index.html'))).toBe(true)
    expect(existsSync(resolve(frontendRoot, 'apps/student/index.html'))).toBe(true)

    const staffConfig = readFileSync(resolve(frontendRoot, 'vite.staff.config.js'), 'utf8')
    const studentConfig = readFileSync(resolve(frontendRoot, 'vite.student.config.js'), 'utf8')

    expect(staffConfig).toContain('port: 3001')
    expect(studentConfig).toContain('port: 3002')
  })
})
