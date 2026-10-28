import { useEffect, useRef, useState } from 'react'
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
  const mathField = useRef(null)
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
    setLatex(existing?.latex || '')
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
  const insertSymbol = (symbol) => {
    replace(symbol)
    setOpen(false)
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
    setOpen(false)
  }

  return <span className="weave-math-tool">
    <button type="button" className={compact ? 'weave-math-tool__trigger weave-math-tool__trigger--compact' : 'weave-math-tool__trigger'} aria-label="Insert mathematics" title="Insert mathematics" disabled={disabled} aria-expanded={open} onClick={remember}>∑{compact ? '' : ' Math'}</button>
    {open && <span className="weave-math-tool__popover" role="dialog" aria-label="Mathematics editor" onKeyDown={(event) => { if (event.key === 'Escape') setOpen(false) }}>
      <span className="weave-math-tool__heading">Quick symbols</span>
      <span className="weave-math-tool__symbols">{SYMBOLS.map((symbol) => <button key={symbol} type="button" title={'Insert ' + symbol} onMouseDown={(e) => e.preventDefault()} onClick={() => insertSymbol(symbol)}>{symbol}</button>)}</span>
      <span className="weave-math-tool__heading">Equation templates</span>
      <span className="weave-math-tool__templates">{TEMPLATES.map(([label, template]) => <button key={label} type="button" onClick={() => addTemplate(template)}>{label}</button>)}</span>
      <span className="weave-math-tool__heading">Visual equation editor</span>
      {ready ? <math-field ref={(element) => {
        if (element && mathField.current !== element) { mathField.current = element; element.value = latex }
        else if (!element) mathField.current = null
      }} aria-label="Equation" onInput={(event) => setLatex(event.target.value)} /> : <span className="weave-math-tool__loading">Loading equation editor…</span>}
      {error && <span role="alert" className="weave-math-tool__error">{error}</span>}
      <span className="weave-math-tool__actions"><button type="button" onClick={() => setOpen(false)}>Cancel</button><button type="button" onClick={insertEquation} disabled={!ready}>Insert equation</button></span>
    </span>}
  </span>
}
