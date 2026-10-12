import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { weaveRequest } from '../src/api/client'
import { ToastHost } from '../src/shared/ui/ToastHost'
import { Notice } from '../src/shared/ui'
import { toastBus } from '../src/shared/ui/useToast'

function response({ status = 200, body = '{}' } = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    statusText: status === 204 ? 'No Content' : 'OK',
    text: vi.fn().mockResolvedValue(status === 204 ? '' : body),
  }
}

describe('shared toast confirmations', () => {
  afterEach(() => {
    act(() => toastBus.clear())
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('shows a Weave-style confirmation after a successful mutation response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ body: '{"id":"exam-1"}' })))
    render(<ToastHost />)

    await act(async () => {
      await weaveRequest('/exams/exam-1/activate', {
        method: 'POST',
        successMessage: 'Examination activated.',
      })
    })

    expect(screen.getByText('Examination activated.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('also confirms successful no-content mutations', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ status: 204 })))
    render(<ToastHost />)

    await act(async () => {
      await weaveRequest('/questions/question-1', {
        method: 'DELETE',
        successMessage: 'Unused question deleted.',
      })
    })

    expect(screen.getByText('Unused question deleted.')).toBeInTheDocument()
  })
  it('routes notices into the shared host even when they mount before it', () => {
    const { container } = render(<><Notice tone="danger">Duplicate examination.</Notice><ToastHost /></>)
    expect(screen.getByRole('alert')).toHaveTextContent('Duplicate examination.')
    expect(container.querySelector('.notice')).toBeNull()
    expect(container.querySelector('.weave-toast--error')).toBeInTheDocument()
  })

  it('keeps errors until dismissed without resurrecting them on unrelated renders', () => {
    vi.useFakeTimers()
    const view = render(<><Notice tone="danger">Failed to save.</Notice><ToastHost /></>)
    act(() => vi.advanceTimersByTime(60000))
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('alert')).not.toHaveClass('is-leaving')
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }))
    expect(screen.getByRole('alert')).toHaveClass('is-leaving')
    act(() => vi.advanceTimersByTime(200))
    view.rerender(<><Notice tone="danger">Failed to save.</Notice><ToastHost /></>)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    view.rerender(<><Notice tone="danger">A different error.</Notice><ToastHost /></>)
    expect(screen.getByRole('alert')).toHaveTextContent('A different error.')
  })

  it('keeps an error visible after its originating page unmounts', () => {
    const view = render(<><Notice tone="danger">Failed to save.</Notice><ToastHost /></>)
    view.rerender(<ToastHost />)
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to save.')
  })

  it('keeps API errors persistent even when a duration is supplied', () => {
    vi.useFakeTimers()
    render(<ToastHost />)
    act(() => toastBus.error('Request failed.', { duration: 1000 }))
    act(() => vi.advanceTimersByTime(60000))
    expect(screen.getByRole('alert')).toHaveTextContent('Request failed.')
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }))
    act(() => vi.advanceTimersByTime(200))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('deduplicates messages and removes scoped notices when the page unmounts', () => {
    const view = render(<><Notice tone="warning">Unavailable.</Notice><Notice tone="warning">Unavailable.</Notice><ToastHost /></>)
    expect(screen.getAllByText('Unavailable.')).toHaveLength(1)
    view.rerender(<ToastHost />)
    expect(screen.queryByText('Unavailable.')).not.toBeInTheDocument()
  })

  it('does not restart an existing success timer when another notification arrives', () => {
    vi.useFakeTimers()
    render(<ToastHost />)
    act(() => toastBus.success('First save.'))
    act(() => vi.advanceTimersByTime(3000))
    act(() => toastBus.success('Second save.'))
    act(() => vi.advanceTimersByTime(1000))
    act(() => vi.advanceTimersByTime(200))
    expect(screen.queryByText('First save.')).not.toBeInTheDocument()
    expect(screen.getByText('Second save.')).toBeInTheDocument()
  })

  it('pauses dismissal while a notification is being read', () => {
    vi.useFakeTimers()
    render(<ToastHost />)
    act(() => toastBus.success('Saved.'))
    fireEvent.mouseEnter(screen.getByRole('status'))
    act(() => vi.advanceTimersByTime(10000))
    expect(screen.getByText('Saved.')).toBeInTheDocument()
    fireEvent.mouseLeave(screen.getByRole('status'))
    act(() => vi.advanceTimersByTime(4000))
    act(() => vi.advanceTimersByTime(200))
    expect(screen.queryByText('Saved.')).not.toBeInTheDocument()
  })

})
