import { readFileSync } from 'node:fs'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { StaffLoginPage } from '../src/features/auth/StaffLoginPage'
import { StudentLoginPage } from '../src/features/auth/StudentLoginPage'

const authCssPath = 'src/features/auth/auth.css'

describe('large-monitor login card alignment', () => {
  it('limits the left offset to staff and student login cards at 1600px+', () => {
    const css = readFileSync(authCssPath, 'utf8')
    const wideRules = css.match(/\/\* Wide monitors:[\s\S]*?(?=\n@media \(max-width: 980px\))/)?.[0]

    expect(wideRules).toBeDefined()
    expect(wideRules).toMatch(/@media screen and \(min-width: 1600px\)/)
    expect(wideRules).toMatch(/\.weave-login-page--staff \.weave-login-card/)
    expect(wideRules).toMatch(/\.weave-login-page--student \.weave-login-card/)
    expect(wideRules).toMatch(/translate: -36px 0;/)
    expect(wideRules).not.toMatch(/(?:\.weave-login-panel|\.weave-login-form\b|\.weave-login-stage-nav)\s*\{/)
  })

  it('centers both login panels only on television-sized viewports', () => {
    const css = readFileSync(authCssPath, 'utf8')
    const tvRules = css.match(/\/\* TV-sized viewports:[\s\S]*?(?=\n@media \(max-width: 980px\))/)?.[0]

    expect(tvRules).toBeDefined()
    expect(tvRules).toMatch(/@media screen and \(min-width: 1680px\) and \(min-height: 850px\)/)
    expect(tvRules).toMatch(/\.weave-login-page\s*\{\s*padding-inline: 0;/)
    expect(tvRules).toMatch(/\.weave-login-welcome\s*\{[^}]*max-width: none;[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/)
    expect(tvRules).toMatch(/\.weave-login-page--staff \.weave-login-card/)
    expect(tvRules).toMatch(/\.weave-login-page--student \.weave-login-card/)
    expect(tvRules).toMatch(/translate: none;/)
  })

  it('keeps staff email and password submission unchanged', () => {
    const onSubmit = vi.fn()
    render(
      <StaffLoginPage
        error=""
        loading={false}
        branding={{ school_name: 'Test School' }}
        onBack={vi.fn()}
        onSubmit={onSubmit}
      />,
    )

    fireEvent.change(screen.getByLabelText(/email address/i), {
      target: { value: '  teacher@example.com  ' },
    })
    fireEvent.change(screen.getByLabelText(/^password$/i), {
      target: { value: 'staff-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      email: 'teacher@example.com',
      password: 'staff-password',
    })
  })

  it('keeps student admission-number and password submission unchanged', () => {
    const onSubmit = vi.fn()
    render(
      <StudentLoginPage
        error=""
        loading={false}
        branding={{ school_name: 'Test School' }}
        onBack={vi.fn()}
        onSubmit={onSubmit}
      />,
    )

    fireEvent.change(screen.getByLabelText(/admission number/i), {
      target: { value: '  abc/24/100  ' },
    })
    fireEvent.change(screen.getByLabelText(/^password$/i), {
      target: { value: 'student-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      admissionNumber: 'ABC/24/100',
      password: 'student-password',
    })
  })
})
