import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { StudentLoginPage } from '../src/features/auth/StudentLoginPage'

describe('StudentLoginPage', () => {
  it('submits admission numbers in the uppercase format required by the backend', () => {
    const onSubmit = vi.fn()

    render(
      <StudentLoginPage
        error=""
        loading={false}
        branding={{ school_name: 'Brightfield Academy' }}
        onBack={vi.fn()}
        onSubmit={onSubmit}
      />,
    )

    fireEvent.change(screen.getByLabelText(/admission number/i), {
      target: { value: ' bfa/24/001 ' },
    })
    fireEvent.change(screen.getByLabelText(/^password$/i), {
      target: { value: 'bfa/24/001' },
    })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      admissionNumber: 'BFA/24/001',
      password: 'bfa/24/001',
    })
  })
})
