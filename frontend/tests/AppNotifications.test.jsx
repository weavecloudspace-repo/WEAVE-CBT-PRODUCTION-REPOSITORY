import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import StaffApp from '../src/app/StaffApp'
import StudentApp from '../src/app/StudentApp'

vi.mock('../src/app/useAppController', () => ({
  useAppController: () => ({
    state: { view: 'boot', installation: { configured: false }, bootError: 'Cannot reach this CBT server.' },
    boot: vi.fn(),
    dispatch: vi.fn(),
  }),
}))

describe('app-wide notification mounting', () => {
  it.each([['staff', StaffApp], ['student', StudentApp]])('shows boot errors as toasts in the %s app', (_, Application) => {
    const { container } = render(<Application />)
    expect(screen.getByRole('alert')).toHaveTextContent('Cannot reach this CBT server.')
    expect(container.querySelector('.weave-toast-host')).toBeInTheDocument()
    expect(container.querySelector('.notice')).toBeNull()
  })
})
