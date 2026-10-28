import { Fragment, useEffect } from 'react'
import { splitMathSegments } from '../math/mathText'
import '../math/math-authoring.css'

const INLINE_FORMAT = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|\^[^^]+\^|\[[^\]]+\]\(https?:\/\/[^)]+\))/g

function MathToken({ latex, display }) {
  useEffect(() => { void import('mathlive').catch(() => {}) }, [])
  return display
    ? <math-div class="weave-math-render weave-math-render--display">{latex}</math-div>
    : <math-span class="weave-math-render">{latex}</math-span>
}

export function FormattedText({ text, placeholder = '' }) {
  const content = text?.trim() || placeholder
  if (!content) return null
  return splitMathSegments(content).map((part, index) => part.math
    ? <MathToken key={index} latex={part.text} display={part.display} />
    : <Fragment key={index}>{part.text.split('\n').map((line, lineIndex) => <Fragment key={lineIndex}>{lineIndex > 0 && <br />}{renderInline(line)}</Fragment>)}</Fragment>)
}

function renderInline(line) {
  return line.split(INLINE_FORMAT).filter(Boolean).map((part, index) => {
    const key = index + '-' + part
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={key}>{part.slice(2, -2)}</strong>
    if (part.startsWith('__') && part.endsWith('__')) return <u key={key}>{part.slice(2, -2)}</u>
    if (part.startsWith('*') && part.endsWith('*')) return <em key={key}>{part.slice(1, -1)}</em>
    if (part.startsWith('^') && part.endsWith('^')) return <sup key={key}>{part.slice(1, -1)}</sup>
    if (part.startsWith('[')) {
      const match = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/)
      if (match) return <a key={key} href={match[2]} target="_blank" rel="noreferrer">{match[1]}</a>
    }
    return <Fragment key={key}>{part}</Fragment>
  })
}
