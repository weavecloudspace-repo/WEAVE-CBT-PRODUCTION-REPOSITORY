import { useCallback, useEffect, useRef, useState, useId } from 'react'
import { createPortal } from 'react-dom'
import { equationAtCursor } from './mathText'
import './math-authoring.css'

const SYMBOLS = ['π', 'θ', 'α', 'β', 'Δ', '×', '÷', '±', '≠', '≤', '≥', '∞', '°']
const TEMPLATES = [
  ['Fraction', '\\frac{1}{2}'],
  ['Square root', '\\sqrt{x}'],
  ['Cube root', '\\sqrt[3]{x}'],
  ['Power', 'x^{2}'],
  ['Subscript', 'x_{1}'],
  ['Sine', '\\sin(\\theta)'],
  ['Cosine', '\\cos(\\theta)'],
  ['Tangent', '\\tan(\\theta)'],
  ['Logarithm', '\\log_{10}(x)'],
  ['Natural log', '\\ln(x)'],
  ['Summation', '\\sum_{i=1}^{n} i'],
  ['Integral', '\\int_0^1 x\\,dx'],
]

export function MathInsertButton({ inputRef, value = '', onChange, compact = false, disabled = false }) {
  const [open, setOpen] = useState(false)
  const [latex, setLatex] = useState('')
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const dialogId = useId()
  const triggerRef = useRef(null)
  const dialogRef = useRef(null)
  const mathField = useRef(null)
  const initialEquation = useRef('')
  const attachMathField = useCallback((element) => {
    mathField.current = element
    if (element) element.value = initialEquation.current
  }, [])
  const selection = useRef({ start: 0, end: 0 })

  useEffect(() => {
    if (!open) return undefined
    let active = true
    import('mathlive').then(() => { if (active) setReady(true) })
      .catch(() => { if (active) setError('The mathematics editor could not load.') })
    return () => { active = false }
  }, [open])

  const remember = () => {
    const el = inputRef?.current
    if (!el) return
    const start = el.selectionStart ?? value.length
    const end = el.selectionEnd ?? start
    const existing = start === end ? equationAtCursor(value, start) : null
    selection.current = existing ? { start: existing.start, end: existing.end } : { start, end }
    initialEquation.current = existing?.latex || ''
    setLatex(initialEquation.current)
    setError('')
    setOpen(true)
  }
  const replace = (text) => {
    const el = inputRef?.current
    if (!el) return
    const { start, end } = selection.current
    onChange(value.slice(0, start) + text + value.slice(end))
    selection.current = { start: start + text.length, end: start + text.length }
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + text.length, start + text.length)
    })
  }
  const closeEditor = useCallback(() => {
    setOpen(false)
    triggerRef.current?.focus()
  }, [])
  const insertSymbol = (symbol) => {
    replace(symbol)
    closeEditor()
  }
  const addTemplate = (template) => {
    if (ready && mathField.current?.insert) {
      mathField.current.insert(template, { selectionMode: 'after' })
      setLatex(mathField.current.value)
      mathField.current.focus()
    } else setLatex((current) => current + template)
  }
  const insertEquation = () => {
    const expression = (mathField.current?.value ?? latex).trim()
    if (!expression) { setError('Enter an equation first.'); return }
    // Use consistent delimiters for all authoring paths.
    replace('\\(' + expression + '\\)')
    closeEditor()
  }

  useEffect(() => {
    if (!open) return undefined

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeEditor()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = [...(dialogRef.current?.querySelectorAll('button:not(:disabled), math-field') || [])]
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    dialogRef.current?.querySelector('.weave-math-tool__close')?.focus()
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, closeEditor])

  return <span className="weave-math-tool">
    <button
      ref={triggerRef}
      type="button"
      className={compact ? 'weave-math-tool__trigger weave-math-tool__trigger--compact' : 'weave-math-tool__trigger'}
      aria-label="Insert mathematics"
      title="Insert mathematics"
      disabled={disabled}
      aria-expanded={open}
      onClick={remember}
    >∑{compact ? '' : ' Math'}</button>
    {open && createPortal(
      <div
        className="weave-math-tool__backdrop"
        onMouseDown={(event) => { if (event.target === event.currentTarget) closeEditor() }}
      >
        <div
          ref={dialogRef}
          className="weave-math-tool__popover"
          role="dialog"
          aria-modal="true"
          aria-labelledby={dialogId}
        >
          <div className="weave-math-tool__header">
            <div>
              <h2 id={dialogId} className="weave-math-tool__title">Equation editor</h2>
              <p className="weave-math-tool__description">Insert a symbol or build a mathematical expression.</p>
            </div>
            <button type="button" className="weave-math-tool__close" aria-label="Close equation editor" onClick={closeEditor}>×</button>
          </div>
          <div className="weave-math-tool__content">
            <section className="weave-math-tool__section" aria-label="Quick symbols">
              <h3 className="weave-math-tool__heading">Quick symbols</h3>
              <div className="weave-math-tool__symbols">
                {SYMBOLS.map((symbol) => <button key={symbol} type="button" title={'Insert ' + symbol} aria-label={'Insert ' + symbol} onMouseDown={(event) => event.preventDefault()} onClick={() => insertSymbol(symbol)}>{symbol}</button>)}
              </div>
            </section>
            <section className="weave-math-tool__section" aria-label="Equation templates">
              <h3 className="weave-math-tool__heading">Equation templates</h3>
              <div className="weave-math-tool__templates">
                {TEMPLATES.map(([label, template]) => <button key={label} type="button" onClick={() => addTemplate(template)}>{label}</button>)}
              </div>
            </section>
            <section className="weave-math-tool__section weave-math-tool__section--editor" aria-label="Visual equation editor">
              <h3 className="weave-math-tool__heading">Visual equation editor</h3>
              {ready
                ? <math-field ref={attachMathField} aria-label="Equation" onInput={(event) => setLatex(event.target.value)} />
                : <div className="weave-math-tool__loading">Loading equation editor…</div>}
              {error && <div role="alert" className="weave-math-tool__error">{error}</div>}
            </section>
          </div>
          <div className="weave-math-tool__actions">
            <button type="button" onClick={closeEditor}>Cancel</button>
            <button type="button" onClick={insertEquation} disabled={!ready}>Insert equation</button>
          </div>
        </div>
      </div>,
      document.body,
    )}
  </span>
}
