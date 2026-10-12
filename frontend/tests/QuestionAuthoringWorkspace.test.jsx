import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionAuthoringWorkspace } from '../src/features/teacher/QuestionAuthoringWorkspace'
import { QuestionBuilder } from '../src/features/teacher/QuestionBuilder'

vi.mock('../src/features/teacher/TeacherAIComposer', () => ({ TeacherAIComposer: ({ onClose }) => <aside aria-label="Question generation"><textarea aria-label="AI prompt" /><button onClick={onClose}>Close question generation</button></aside> }))

let measureWorkspace
beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('PointerEvent', MouseEvent)
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback) { measureWorkspace = (width) => callback([{ contentRect: { width } }]) }
    observe() { measureWorkspace(1600) }
    disconnect() {}
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Resizable teacher AI workspace', () => {
  it('resizes with pointer and keyboard, clamps, and remembers width', () => {
    const { container, unmount } = render(<QuestionAuthoringWorkspace open panel={<p>Assistant</p>}><p>Editor</p></QuestionAuthoringWorkspace>)
    const divider = screen.getByRole('separator', { name: 'Resize AI panel' })
    divider.setPointerCapture = vi.fn()
    fireEvent.pointerDown(divider, { button: 0, clientX: 800, pointerId: 1 })
    fireEvent.pointerMove(divider, { clientX: 700, pointerId: 1 })
    fireEvent.pointerUp(divider, { pointerId: 1 })
    expect(divider).toHaveAttribute('aria-valuenow', '480')
    fireEvent.keyDown(divider, { key: 'ArrowLeft' })
    expect(divider).toHaveAttribute('aria-valuenow', '500')
    fireEvent.keyDown(divider, { key: 'End' })
    expect(divider).toHaveAttribute('aria-valuenow', '640')
    fireEvent.keyDown(divider, { key: 'Home' })
    expect(divider).toHaveAttribute('aria-valuenow', '300')
    expect(container.firstChild.style.getPropertyValue('--ai-panel-width')).toBe('300px')
    unmount()
    render(<QuestionAuthoringWorkspace open panel={<p>Assistant</p>}><p>Editor</p></QuestionAuthoringWorkspace>)
    expect(screen.getByRole('separator')).toHaveAttribute('aria-valuenow', '300')
  })

  it('uses a generation toggle and preserves both inputs when closing and reopening', () => {
    const subject = { id: 'subject-1', name: 'English', academicLevelId: 'level-1', academicLevelName: 'JSS 1' }
    const bank = { id: 'bank-1', name: 'English JSS 1', curriculumSubjectId: subject.id, academicLevelId: subject.academicLevelId }
    render(<QuestionBuilder enableAI state={{ staff: { section: 'create-question', selectedBankId: bank.id } }} teacherData={{ banks: [bank], subjects: [subject] }} dispatch={vi.fn()} gateway={{}} />)
    expect(screen.queryByRole('separator')).not.toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: 'Open question generation' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.change(screen.getByRole('textbox', { name: 'Question prompt' }), { target: { value: 'Keep my manual question' } })
    fireEvent.click(toggle)
    expect(screen.getByRole('separator')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'AI prompt' }), { target: { value: 'Keep my AI prompt' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Close question generation' })[1])
    expect(screen.queryByRole('separator')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Question prompt' })).toHaveValue('Keep my manual question')
    fireEvent.click(screen.getByRole('button', { name: 'Open question generation' }))
    expect(screen.getByRole('textbox', { name: 'AI prompt' })).toHaveValue('Keep my AI prompt')
  })

  it('clamps remembered widths to the available admin pane and restores them on expansion', () => {
    localStorage.setItem('weave.teacher.aiPanelWidth', '640')
    const { container } = render(<QuestionAuthoringWorkspace open panel={<p>Assistant</p>}><p>Editor</p></QuestionAuthoringWorkspace>)
    const divider = screen.getByRole('separator')
    expect(divider).toHaveAttribute('aria-valuenow', '640')
    act(() => measureWorkspace(980))
    expect(divider).toHaveAttribute('aria-valuemax', '411')
    expect(container.firstChild.style.getPropertyValue('--ai-panel-width')).toBe('411px')
    act(() => measureWorkspace(900))
    expect(divider).toHaveAttribute('aria-valuenow', '335')
    act(() => measureWorkspace(1600))
    expect(divider).toHaveAttribute('aria-valuenow', '640')
    expect(localStorage.getItem('weave.teacher.aiPanelWidth')).toBe('640')
  })
})
