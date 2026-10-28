import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { StaffLoginPage } from '../src/features/auth/StaffLoginPage'
import { StudentLoginPage } from '../src/features/auth/StudentLoginPage'
import { FormField } from '../src/shared/ui'

describe.each([
  {
    kind: 'staff',
    Page: StaffLoginPage,
    identityLabel: /email address/i,
    identity: 'teacher@example.com',
    expectedCredentials: { email: 'teacher@example.com', password: 'wrong-Password123' },
  },
  {
    kind: 'student',
    Page: StudentLoginPage,
    identityLabel: /admission number/i,
    identity: 'JSS1/2026/101',
    expectedCredentials: { admissionNumber: 'JSS1/2026/101', password: 'wrong-Password123' },
  },
])('$kind password field', ({ Page, identityLabel, identity, expectedCredentials }) => {
  it('keeps an accessible reveal button visible when empty or filled without changing the submitted password', () => {
    const onSubmit = vi.fn()
    render(
      <Page
        error=""
        loading={false}
        branding={{ school_name: 'Test School' }}
        onBack={vi.fn()}
        onSubmit={onSubmit}
      />,
    )

    const passwordInput = screen.getByLabelText(/^password$/i)
    const reveal = screen.getByRole('button', { name: 'Show password' })
    expect(passwordInput).toHaveAttribute('type', 'password')
    expect(reveal).toBeVisible()
    expect(reveal).toHaveAttribute('type', 'button')
    expect(reveal).toHaveAttribute('aria-pressed', 'false')

    // The reveal icon must work even before the user enters anything.
    fireEvent.click(reveal)
    expect(passwordInput).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Hide password' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.change(screen.getByLabelText(identityLabel), { target: { value: identity } })
    fireEvent.change(passwordInput, { target: { value: 'wrong-Password123' } })
    expect(passwordInput).toHaveValue('wrong-Password123')

    fireEvent.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(passwordInput).toHaveAttribute('type', 'password')
    expect(passwordInput).toHaveValue('wrong-Password123')
    expect(screen.getByRole('button', { name: 'Show password' })).toBeVisible()

    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))
    expect(onSubmit).toHaveBeenCalledWith(expectedCredentials)
  })
})

describe('shared FormField password control', () => {
  it('continues to show the eye button before typing and communicates reveal state', () => {
    render(<FormField label="Password" type="password" value="" onChange={vi.fn()} />)

    const passwordInput = screen.getByLabelText(/^password$/i)
    const showButton = screen.getByRole('button', { name: 'Show password' })
    expect(passwordInput).toHaveAttribute('type', 'password')
    expect(showButton).toBeVisible()
    expect(showButton).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(showButton)
    expect(passwordInput).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Hide password' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(passwordInput).toHaveAttribute('type', 'password')
    expect(screen.getByRole('button', { name: 'Show password' })).toBeVisible()
  })

  it('does not render an eye button for non-password fields', () => {
    render(<FormField label="Email" type="email" value="" onChange={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Show password' })).not.toBeInTheDocument()
  })
})
