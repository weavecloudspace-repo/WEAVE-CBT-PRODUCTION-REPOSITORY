import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { LandingPage } from '../src/features/landing/LandingPage'

describe('split frontend entrypoints', () => {
  it('shows only staff sign-in from the staff application landing page', () => {
    const dispatch = vi.fn()

    render(<LandingPage dispatch={dispatch} audience="staff" />)

    expect(screen.getByRole('button', { name: /login as staff/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /login as student/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /login as staff/i }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'view', view: 'staff-login' })
  })

  it('shows only student sign-in from the student application landing page', () => {
    const dispatch = vi.fn()

    render(<LandingPage dispatch={dispatch} audience="student" />)

    expect(screen.getByRole('button', { name: /login as student/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /login as staff/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /login as student/i }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'view', view: 'student-login' })
  })
})
