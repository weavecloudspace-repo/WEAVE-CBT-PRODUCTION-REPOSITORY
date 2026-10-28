import { useRef, useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FormattedText } from '../src/shared/ui/FormattedText'
import { MathInsertButton } from '../src/shared/math/MathInsertButton'
import { equationAtCursor, normalizeMathText, splitMathSegments } from '../src/shared/math/mathText'

describe('shared CBT mathematical text normalization', () => {
  it('normalizes AI dollar math, display math, and bare mathematical commands', () => {
    const value = String.raw`Calculate $\frac{2}{3}$, $$x^2=4$$ and \sqrt{9}`
    const result = normalizeMathText(value)
    expect(result).toContain(String.raw`\(\frac{2}{3}\)`)
    expect(result).toContain(String.raw`\[x^2=4\]`)
    expect(result).toContain(String.raw`\(\sqrt{9}\)`)
    expect(splitMathSegments(value).filter((part) => part.math)).toHaveLength(3)
  })

  it('recognizes bare AI trigonometry and logarithms without changing ordinary words', () => {
    const parts = splitMathSegments(String.raw`Calculate \sin 30^\circ and \log_{10}(100) then solve $x$`)
    expect(parts.filter((part) => part.math).map((part) => part.text)).toEqual([
      String.raw`\sin 30^\circ`,
      String.raw`\log_{10}(100)`,
      'x',
    ])
  })

  it('preserves currency and ordinary formatting', () => {
    expect(splitMathSegments('The price is $10 and $20 today').filter((part) => part.math)).toHaveLength(0)
    const { container } = render(<FormattedText text="This is **important** and x²" />)
    expect(container.querySelector('strong')).toHaveTextContent('important')
    expect(container).toHaveTextContent('x²')
  })

  it('renders formulas in the same renderer used by student previews', () => {
    const { container } = render(<FormattedText text={String.raw`Solve \(\frac{x}{2}=5\) or $$x^2=4$$`} />)
    expect(container.querySelector('math-span')).toBeTruthy()
    expect(container.querySelector('math-div')).toBeTruthy()
    expect(container).toHaveTextContent('Solve')
  })

  it('detects an existing equation for visual re-editing', () => {
    const source = String.raw`Find \(\sqrt{25}\) now`
    expect(equationAtCursor(source, 10)).toEqual({ start: 5, end: 18, latex: String.raw`\sqrt{25}`, display: false })
  })
})

function EditorHarness() {
  const [text, setText] = useState('Calculate  now')
  const ref = useRef(null)
  return <><textarea ref={ref} aria-label="Question prompt" value={text} onChange={(event) => setText(event.target.value)} />
    <MathInsertButton inputRef={ref} value={text} onChange={setText} /></>
}

describe('manual and AI editor mathematics insertion', () => {
  it('inserts quick symbols at the existing caret position', () => {
    vi.stubGlobal('requestAnimationFrame', (callback) => { callback(); return 1 })
    render(<EditorHarness />)
    const field = screen.getByLabelText('Question prompt')
    field.focus()
    field.setSelectionRange(10, 10)
    fireEvent.click(screen.getByRole('button', { name: 'Insert mathematics' }))
    fireEvent.click(screen.getByRole('button', { name: 'Insert π' }))
    expect(field).toHaveValue('Calculate π now')
    vi.unstubAllGlobals()
  })
})
